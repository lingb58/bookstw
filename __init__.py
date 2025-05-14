from __future__ import absolute_import, division, print_function, unicode_literals

import re
try:
    from queue import Queue
except ImportError:
    from Queue import Queue

from calibre.ebooks.metadata.book.base import Metadata
from calibre.ebooks.metadata.sources.base import Source
from calibre.utils.localization import canonicalize_lang
from lxml import html

class BooksTW(Source):

    name = 'BooksTW'
    description = 'Download metadata from books.com.tw'
    supported_platforms = ['windows', 'osx', 'linux']
    author              = 'Robin Lin'  # The author of this plugin
    version             = (0, 0, 1)   # The version number of this plugin
    can_get_multiple_covers = False
    prefer_results_with_isbn = True
    supports_search_by_isbn = True

    _query_count = 0
    MAX_QUERY_COUNT = 5

    capabilities = frozenset(['identify'])#, 'cover'])
    touched_fields = frozenset([
        'identifier:isbn', 'identifier:bookstw', 'title', 'authors','rating', 
        'comments', 'publisher', 'pubdate', 'tags', 'languages'])  # 'series',

    BASE_URL = 'https://www.books.com.tw'

    def identify(self, log, result_queue, abort, title=None, authors=None,
            identifiers={}, timeout=30):
        books = None
        self._query_count = 0
        items = list(identifiers.items())
        try:
            if items:
                # try to find the book by identifiers
                for id_type, val in items:
                    if id_type.lower() == 'isbn':
                        books = self.search_books(log, val, timeout=timeout)
                        break
                    if id_type.lower() == 'bookstw':
                        books = self.search_books(log, val, timeout=timeout)
                        break
            if not books:
                query_string = ""
                if title:
                    query_string += " " + title
                if authors:
                    query_string += " " + ' '.join(authors)
                books = self.search_books(log, query_string, timeout=timeout)
        except Exception as e:
            log.error(f'Search failed: {e}')
        
        if not books:
            log.info("Can't find relative book.")

        for book in books:
            try:
                one = self.download_metadata(log, result_queue, book, timeout=timeout)
                if one:
                    result_queue.put(one)
            except Exception as e:
                log.error(f'Download metadata failed ({book}): {e}')

    def search_books(self, log, key, timeout=30):
        SEARCH_URL = 'https://search.books.com.tw/search/query/key/%s/cat/BKA'
        url = SEARCH_URL % key

        try:
            r = self.browser.open(url, timeout=timeout)
            raw = r.read()
            doc = html.fromstring(raw.decode('utf-8'))
        except Exception as e:
            log.error(f'Open book page failed: {e}')
            return None

        if '很抱歉，您搜尋的商品已下架' in doc or '抱歉，找不到您所查詢的' in doc:
            log.info(f"Can't find the keyword: {key}")
            return None

        books = []
        for data in doc.xpath('//div[@class="table-searchbox clearfix"]'):
            for book_url in data.xpath('.//div[@class="box"]/a//@href'):
                log.info(f"book_url: {book_url}")
                if not book_url:
                    continue
                m = re.search('item\/(..\d+)', book_url)
                log.info(f"book item: {m.group(1)}")
                books.append(m.group(1))
        return books 
        
    def download_metadata(self, log, result_queue, book_id, timeout=30):
        BOOK_URL_PATTERN = 'https://www.books.com.tw/products/%s'
        book_url = BOOK_URL_PATTERN % book_id
        log.info(f"Grabbing  {book_id}, {book_url}")
        if self._query_count >= self.MAX_QUERY_COUNT:
            return
        else:
            self._query_count += 1

        touched = []
        try:
            r = self.browser.open(book_url, timeout=timeout)
            raw = r.read()
            doc = html.fromstring(raw.decode('utf-8'))
        except Exception as e:
            log.error(f'open page failed ({book_url}): {e}')
            return
        
        lang_map = {
            '英文':'en',
            '繁體中文':'zh',
            '簡體中文':'zh',
            }
        cover_url = ''.join(doc.xpath('.//div[@class="cnt_mod002 cover_img"]/img/@src'))
        log.info("cover_url: " + cover_url)
        self.cache_identifier_to_cover_url(book_id, cover_url)

        title = ''.join(doc.xpath('.//div[@class="mod type02_p002 clearfix"]/h1/text()')).strip()
        log.info(f"doc.title: {title}")
        sub_title = ''.join(doc.xpath('.//div[@class="mod type02_p002 clearfix"]/h2/a/text()')).strip()
        log.info(f"doc.sub_title: {sub_title}")
        if sub_title:
            title += ' ' + sub_title
        log.info("title: " + title)
        touched.append('title')

        book_info_block = doc.xpath('.//div[@class="type02_p003 clearfix"]/ul/li')
        log.info(f"doc.book_info_block: {book_info_block}")
        if not book_info_block:
            return None
        
        authors = []
        for info in book_info_block:
            info_itertext = "".join(info.itertext())
            if info_itertext and "作者：" in info_itertext:
                candidate = info_itertext.splitlines()
                log.info(f"candidate: {candidate}")
                for a in candidate:
                    if "作者：" in a and "修改" not in a:
                        author_line = a.replace("原文作者：", "").replace("作者：", "").strip()
                        for author in re.split(',| ', author_line):
                            if len(author) > 0:
                                log.info("作者: " + author)
                                authors.append(author)
                touched.append('authors')
                continue
            if info.text and "出版社：" in info.text:
                publisher = "".join(info.itertext())
                end = len(publisher)
                if '\n' in publisher:
                    end = publisher.index("\n")
                publisher = publisher[publisher.index("：")+1:end]
                log.info("出版社: " + publisher)
                touched.append('publisher')
                continue
            if info.text and "出版日期：" in info.text:
                pubdate = info.text.replace("出版日期：", "")
                log.info("出版日期: " + pubdate)
                continue
            if info.text and "語言：" in info.text:
                lang = info.text.replace("語言：", "").strip()#.replace("英文", "英語")
                lang = lang_map[lang]
                log.info("lang: " + lang)
                touched.append('language')
                continue

        meta = Metadata(title, authors)
        contents = doc.xpath('//div[@class="mod_b type02_m057 clearfix"]')
        for a in contents:
            itertext = ''.join(a.itertext())
            if '內容簡介' in itertext:
                comments = itertext.replace('內容簡介', "")
                while "\n\n" in comments:
                    comments = comments.replace("\n\n", "\n")
        meta.comments = comments
        touched.append('comments')

        isbn = ''.join(doc.xpath('//div[@class="mod_b type02_m058 clearfix"]/div/ul[1]/li[1]/text()')).removeprefix("ISBN：")
        if isbn:
            self.cache_identifier_to_cover_url(isbn, cover_url)
        meta.identifiers = {'isbn': isbn, 'bookstw': book_id}
        touched.append('identifier:isbn')
        touched.append('identifier:bookstw')

        meta.publisher = publisher
        log.info("publisher: " + meta.publisher)

        if pubdate:
            from calibre.utils.date import parse_date, utcnow
            try:
                default = utcnow().replace(day=15)
                meta.pubdate = parse_date(pubdate, assume_utc=True, default=default)
                touched.append('pubdate')
            except:
                log.error('Failed to parse pubdate %r' % pubdate)

        language = canonicalize_lang(lang)
        if language:
            meta.language = language
        else:
            meta.language = None
        log.info("language: " + meta.language)
        touched.append('language')

        rate = ''.join(doc.xpath('.//div[@class="bui-stars star-s"]/span/@title')).strip()
        log.info(f"rate: {rate}")
        if rate:
            meta.rating = float(rate[0:1])
            if meta.rating > 0.0:
                touched.append('rating')
                log.info(f"rating: {meta.rating}")

        tags = []
        tag_text = ''.join(doc.xpath('.//ul[@class="sort"]//text()')).strip()
        log.info(f"tag_text: {tag_text}")
        tag_text = tag_text.replace("本書分類：", "").replace(" ", "")
        tags = tag_text.split(">")
        log.info(f"tags: {tags}")
        meta.tags = tags
        touched.append('tags')

        meta.has_cover = False
        meta.source_relevance = 0
        self.touched_fields = frozenset(touched)
        return meta

    def download_cover(self, log, result_queue, abort,  # {{{
                       title=None, authors=None, identifiers={}, timeout=60, get_best_cover=False):
        log.info(f"try to download the cover image")
        cached_url = None
        for id in identifiers:
            log.info(f"id: {id}")
            val = identifiers[id]
            log.info(f"identifiers: {val}")
            if ('bookstw' == id or 'isbn' == id) and val:
                log.info(f"1 identifiers: {id}, {val}")
                try:
                    cached_url = self.cached_identifier_to_cover_url(val)
                    log.info(f"1 cached_url: {cached_url}")
                except Exception as e:
                    log.info(f"can't find the cover")
                    break
        
        if cached_url is None:
            log.info('No cached cover found, running identify')
            rq = Queue()
            try:
                self.identify(log, rq, abort, title=title, authors=authors, identifiers=identifiers)
            except Exception as e:
                log.info(f"can't find the cover")
            for mi in rq:
                for id, val in mi.identifiers:
                    if ('bookstw' == id or 'isbn' == id) and val:
                        log.info(f"2 identifiers: {id}, {val}")
                        cached_url = self.cached_identifier_to_cover_url(val)
                        log.info(f"2 cached_url: {cached_url}")
                        break
        
        image = None
        try:
            image = self.browser.open(cached_url, timeout=timeout).read()
        except Exception as e:
            log.info(f"download image failed: {e}")
        if image:
            result_queue.put((self, image))
            log.info(f"image put into result_queue")

if __name__ == '__main__':  # tests
    # To run these test use:
    # calibre-debug -e __init__.py
    from calibre.ebooks.metadata.sources.test import (test_identify_plugin,
            title_test, authors_test, series_test)
    test_identify_plugin(BooksTW.name,
        [
            (# A book with an ISBN
                {'identifiers': {'isbn': '9787302527459'}},
                [ title_test('ROS2源代碼分析與工程應用', exact=True), authors_test(['丁亮']) ]
            ),
            # (# A book with an ISBN
            #     {'identifiers': {'isbn': '9789866272547'}},
            #     [ title_test('攝影師的四大修練：打破規則的觀察、想像、表現、視覺設計，拍出大師級作品 Photography and the Art of Seeing: A Visual Perception Workshop for Film and Digital Photography', exact=True), authors_test(['patterson', 'freeman', '佛利曼．帕德遜']) ]
            # ),
            # (# A book with an ISBN
            #     {'identifiers': {'isbn': '9787532770243'}},
            #     [ title_test('石黑一雄（Kazuo Ishiguro）文集:被掩埋的巨人', exact=True), authors_test(['（英）石黑一雄']) ]
            # ),
            # (# A book with an ISBN
            #     {'identifiers': {'isbn': '9787802491830'}},
            #     [ title_test('再啟動︰獲取職場生存與發展的原動力', exact=True), authors_test(['[日]大前研一']) ]
            # ),
            # (# A book with an ISBN
            #     { 'identifiers': { 'isbn': '9781596591707' } },
            #     [ title_test('The First Time Manager', exact=True), authors_test(['topchik', 'belker', 'b./', 'pratt', 'sean', 'loren', '(nrt)', 's./', 'gary']) ]
            # ),
            # (# A book with an ISBN
            #     { 'identifiers':{'isbn': '9780593420584'} },
            #     [ title_test('Ideaflow: The Only Business Metric That Matters', exact=True), authors_test(['klebahn', 'perry', 'jeremy', 'utley']) ]
            # ),
            # (# A book with no ISBN specified
            #     { 'title':"BCG問題解決力：一生受用的策略顧問思考法", 'authors':['徐瑞廷'] },
            #     [ title_test("BCG問題解決力：一生受用的策略顧問思考法", exact=True), authors_test(['徐瑞廷', '黃菁媺'])]
            # ),
            # (# A book with no ISBN specified
            #     { 'title':"再啟動︰獲取職場生存與發展的原動力", 'authors':['[日]大前研一'] },
            #     [ title_test("再啟動︰獲取職場生存與發展的原動力", exact=True), authors_test(['[日]大前研一'])]
            # ),
        ])