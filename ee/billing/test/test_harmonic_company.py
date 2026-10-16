from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from ee.billing.salesforce_enrichment.harmonic_company import is_sub_entity, website_path_is_root


class TestWebsitePathIsRoot(SimpleTestCase):
    @parameterized.expand(
        [
            ("bare_root", "https://example.com", True),
            ("trailing_slash", "https://example.com/", True),
            ("index_html", "https://example.com/index.html", True),
            ("default_aspx", "https://example.com/default.aspx", True),
            ("home_html", "https://example.com/home.html", True),
            ("language_segment", "https://example.com/en", True),
            ("language_segment_trailing_slash", "https://example.com/en/", True),
            ("language_with_region", "https://example.com/de-at", True),
            ("language_with_script", "https://example.com/zh-Hant", True),
            ("language_with_script_and_region", "https://example.com/zh-Hant-TW", True),
            ("language_with_numeric_region", "https://example.com/es-419", True),
            ("country_segment", "https://example.com/us", True),
            ("country_then_language", "https://example.com/us-en", True),
            ("rare_language", "https://example.com/cy", True),
            ("schemeless_domain", "example.com", True),
            ("schemeless_www_with_slash", "www.example.com/", True),
            ("hash_route_on_the_root", "https://example.com/#/overview", True),
            ("unparseable_url", "https://[broken", True),
            ("two_letters_that_are_not_a_language_or_country", "https://example.com/ds", False),
            ("nested_path", "https://example.com/ventures/fund", False),
            ("country_then_language_file", "https://example.com/us/en.html", False),
            ("product_path", "https://example.com/products/widgets", False),
            ("hash_route_under_a_path", "https://example.com/portal/#/overview", False),
            ("login_page", "https://example.com/login", False),
        ]
    )
    def test_website_path_is_root(self, _name: str, url: str, expected: bool) -> None:
        assert website_path_is_root(url) is expected


class TestIsSubEntity(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_website_key", {"name": "Example Corp"}, False),
            ("website_not_a_dict", {"website": "https://example.com/ventures"}, False),
            ("null_url", {"website": {"url": None}}, False),
            ("empty_url", {"website": {"url": ""}}, False),
            ("root_url", {"website": {"url": "https://example.com/"}}, False),
            ("path_url", {"website": {"url": "https://example.com/ventures"}}, True),
        ]
    )
    def test_is_sub_entity(self, _name: str, company: dict[str, Any], expected: bool) -> None:
        assert is_sub_entity(company) is expected
