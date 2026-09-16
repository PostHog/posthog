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
