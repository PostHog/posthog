import pytest

from parameterized import parameterized

from posthog.hogql.errors import QueryError

from posthog.hogql_queries.insights.trends.breakdown import cohort_breakdown_value_to_int


class TestCohortBreakdownValueToInt:
    @parameterized.expand(
        [
            ("all_string", "all", 0),
            ("zero_string", "0", 0),
            ("numeric_string", "42", 42),
            ("numeric_int", 42, 42),
        ]
    )
    def test_returns_cohort_id(self, _name, value, expected):
        assert cohort_breakdown_value_to_int(value) == expected

    @parameterized.expand(
        [
            ("object_key", "id"),
            ("null_label", "null"),
            ("display_label", "United States"),
            ("empty", ""),
        ]
    )
    def test_non_cohort_id_raises_query_error(self, _name, value):
        # A cohort breakdown shaped as an object reaches this coercion as a key string like "id".
        # It must surface a handled QueryError, not an unhandled ValueError that 500s the query.
        with pytest.raises(QueryError):
            cohort_breakdown_value_to_int(value)
