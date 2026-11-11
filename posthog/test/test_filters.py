from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.filters import term_search_filter_sql


class TestTermSearchFilterSql(SimpleTestCase):
    @parameterized.expand(
        [
            ("trigram_index", False, "AND (((name ilike %(search_0)s OR alias ilike %(search_1)s)) )"),
            (
                "project_scan",
                True,
                "AND (((lower(name) like lower(%(search_0)s) OR lower(alias) like lower(%(search_1)s))) )",
            ),
        ]
    )
    def test_predicate_form_follows_index_choice(self, _name: str, avoid_trigram_index: bool, expected: str) -> None:
        sql, params = term_search_filter_sql(["name", "alias"], "Foo", avoid_trigram_index=avoid_trigram_index)

        assert sql == expected
        assert params == {"search_0": "%Foo%", "search_1": "%Foo%"}

    @parameterized.expand(
        [
            ("underscore", "$mcp_tool_name", "%$mcp\\_tool\\_name%"),
            ("percent", "50%", "%50\\%%"),
            ("trailing backslash", "a\\", "%a\\\\%"),
        ]
    )
    def test_like_wildcards_in_a_term_match_literally(self, _name: str, term: str, expected_pattern: str) -> None:
        _, params = term_search_filter_sql(["name"], term)

        assert params == {"search_0": expected_pattern}
