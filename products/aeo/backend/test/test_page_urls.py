from django.db import connection
from django.test import SimpleTestCase, TestCase

from parameterized import parameterized

from products.aeo.backend.page_urls import page_url, page_url_sql

CASES = [
    ("https://example.com/docs?utm_source=openai", "https://example.com/docs"),
    ("https://example.com/docs?utm_source=chatgpt.com&utm_medium=referral", "https://example.com/docs"),
    ("https://example.com/docs?id=7&utm_source=openai", "https://example.com/docs?id=7"),
    ("https://example.com/docs?utm_source=openai&id=7", "https://example.com/docs?id=7"),
    ("https://example.com/docs?UTM_Source=openai#install", "https://example.com/docs#install"),
    ("https://example.com/docs?gclid=abc&page=2&fbclid=x", "https://example.com/docs?page=2"),
    ("https://example.com/docs?utm_content", "https://example.com/docs"),
    ("https://example.com/docs?trk=article-ssr-frontend-pulse_little-text-block", "https://example.com/docs"),
    # A parameter that only starts like a tracking one picks content, so it stays.
    ("https://example.com/search?utmost=1", "https://example.com/search?utmost=1"),
    ("https://example.com/docs", "https://example.com/docs"),
    ("https://example.com/docs?", "https://example.com/docs"),
    # Only the query changes: a fragment, a path or a host that looks like a parameter stays as written.
    ("https://example.com/docs?utm_source=x#section?utm_source=y", "https://example.com/docs#section?utm_source=y"),
    ("https://example.com/docs#install?utm_source=x", "https://example.com/docs#install?utm_source=x"),
    ("https://example.com/docs&trk=part/details", "https://example.com/docs&trk=part/details"),
    ("https://evil.example&trk=@example.com/page", "https://evil.example&trk=@example.com/page"),
]


class TestPageUrl(SimpleTestCase):
    @parameterized.expand(CASES)
    def test_drops_tracking_parameters(self, url: str, expected: str) -> None:
        assert page_url(url) == expected

    @parameterized.expand(CASES)
    def test_is_stable_when_applied_again(self, url: str, _expected: str) -> None:
        # Rankings hands a page URL it already cleaned to the citations lookup, which cleans it again.
        assert page_url(page_url(url)) == page_url(url)


class TestPageUrlSql(TestCase):
    def test_matches_the_python_rule(self) -> None:
        # The reads group in SQL and the citations lookup compares with the Python rule, so the two must agree.
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {page_url_sql('url')} FROM unnest(%s::text[]) WITH ORDINALITY AS t(url, n) ORDER BY n",
                [[url for url, _ in CASES]],
            )
            rows = [row[0] for row in cursor.fetchall()]
        assert rows == [expected for _, expected in CASES]
