from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.filters import term_search_filter_sql


class TestTermSearchFilterSql(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "trigram_index",
                False,
                "AND ((((name ilike %(search_pattern_0)s AND strpos(lower(name), lower(%(search_term_0)s)) > 0)"
                " OR (alias ilike %(search_pattern_0)s AND strpos(lower(alias), lower(%(search_term_0)s)) > 0))) )",
                {"search_term_0": "Foo", "search_pattern_0": "%Foo%"},
            ),
            (
                "project_scan",
                True,
                "AND (((strpos(lower(name), lower(%(search_term_0)s)) > 0"
                " OR strpos(lower(alias), lower(%(search_term_0)s)) > 0)) )",
                {"search_term_0": "Foo"},
            ),
        ]
    )
    def test_predicate_form_follows_index_choice(
        self, _name: str, avoid_trigram_index: bool, expected_sql: str, expected_params: dict[str, str]
    ) -> None:
        sql, params = term_search_filter_sql(["name", "alias"], "Foo", avoid_trigram_index=avoid_trigram_index)

        assert sql == expected_sql
        assert params == expected_params

    @parameterized.expand(
        [
            ("underscore stays a wildcard", "$mcp_tool_name", "%$mcp_tool_name%"),
            ("percent stays a wildcard", "50%", "%50%%"),
            ("backslash is escaped", "a\\", "%a\\\\%"),
        ]
    )
    def test_trigram_candidate_pattern(self, _name: str, term: str, expected_pattern: str) -> None:
        _, params = term_search_filter_sql(["name"], term)

        assert params == {"search_term_0": term, "search_pattern_0": expected_pattern}
