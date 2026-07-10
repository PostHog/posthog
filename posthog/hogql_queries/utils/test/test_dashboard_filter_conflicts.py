from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import (
    CohortPropertyFilter,
    EventPropertyFilter,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    PersonPropertyFilter,
    PropertyOperator,
)

from posthog.hogql_queries.utils.dashboard_filter_conflicts import drop_conflicting_insight_filters


def event_filter(key: str = "utm_medium", operator: PropertyOperator = PropertyOperator.EXACT, value=None):
    return EventPropertyFilter(key=key, operator=operator, value=value)


class TestDropConflictingInsightFilters(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "exact_vs_is_not_same_value",
                event_filter(operator=PropertyOperator.EXACT, value="abc"),
                event_filter(operator=PropertyOperator.IS_NOT, value="abc"),
                True,
            ),
            (
                "is_not_vs_exact_same_value",
                event_filter(operator=PropertyOperator.IS_NOT, value="abc"),
                event_filter(operator=PropertyOperator.EXACT, value="abc"),
                True,
            ),
            (
                "exact_subset_of_is_not_values",
                event_filter(operator=PropertyOperator.EXACT, value=["a"]),
                event_filter(operator=PropertyOperator.IS_NOT, value=["a", "b"]),
                True,
            ),
            (
                "exact_vs_is_not_partial_overlap_satisfiable",
                event_filter(operator=PropertyOperator.EXACT, value=["a", "b"]),
                event_filter(operator=PropertyOperator.IS_NOT, value=["a"]),
                False,
            ),
            (
                "exact_vs_exact_disjoint_values",
                event_filter(operator=PropertyOperator.EXACT, value="abc"),
                event_filter(operator=PropertyOperator.EXACT, value="xyz"),
                True,
            ),
            (
                "exact_vs_exact_overlapping_values",
                event_filter(operator=PropertyOperator.EXACT, value=["a", "b"]),
                event_filter(operator=PropertyOperator.EXACT, value=["b", "c"]),
                False,
            ),
            (
                "in_vs_not_in_same_value",
                event_filter(operator=PropertyOperator.IN_, value=["a"]),
                event_filter(operator=PropertyOperator.NOT_IN, value=["a"]),
                True,
            ),
            (
                "is_set_vs_is_not_set",
                event_filter(operator=PropertyOperator.IS_SET),
                event_filter(operator=PropertyOperator.IS_NOT_SET),
                True,
            ),
            (
                "exact_vs_is_not_set",
                event_filter(operator=PropertyOperator.EXACT, value="abc"),
                event_filter(operator=PropertyOperator.IS_NOT_SET),
                True,
            ),
            (
                "icontains_vs_is_not_set",
                event_filter(operator=PropertyOperator.ICONTAINS, value="abc"),
                event_filter(operator=PropertyOperator.IS_NOT_SET),
                True,
            ),
            (
                "regex_vs_is_not_set",
                event_filter(operator=PropertyOperator.REGEX, value="abc.*"),
                event_filter(operator=PropertyOperator.IS_NOT_SET),
                True,
            ),
            (
                "is_not_vs_is_not_set_satisfiable_on_unset",
                event_filter(operator=PropertyOperator.IS_NOT, value="abc"),
                event_filter(operator=PropertyOperator.IS_NOT_SET),
                False,
            ),
            (
                "icontains_vs_not_icontains_same_needle_case_insensitive",
                event_filter(operator=PropertyOperator.ICONTAINS, value="Docs"),
                event_filter(operator=PropertyOperator.NOT_ICONTAINS, value="docs"),
                True,
            ),
            (
                "icontains_vs_not_icontains_excluded_substring_of_included",
                event_filter(operator=PropertyOperator.ICONTAINS, value="docs"),
                event_filter(operator=PropertyOperator.NOT_ICONTAINS, value="doc"),
                True,
            ),
            (
                "icontains_vs_not_icontains_included_substring_of_excluded_satisfiable",
                event_filter(operator=PropertyOperator.ICONTAINS, value="doc"),
                event_filter(operator=PropertyOperator.NOT_ICONTAINS, value="docs"),
                False,
            ),
            (
                "icontains_vs_not_icontains_unrelated_needles",
                event_filter(operator=PropertyOperator.ICONTAINS, value="docs"),
                event_filter(operator=PropertyOperator.NOT_ICONTAINS, value="api"),
                False,
            ),
            (
                "regex_vs_not_regex_identical_pattern",
                event_filter(operator=PropertyOperator.REGEX, value="^/docs/.*"),
                event_filter(operator=PropertyOperator.NOT_REGEX, value="^/docs/.*"),
                True,
            ),
            (
                "regex_vs_not_regex_different_patterns",
                event_filter(operator=PropertyOperator.REGEX, value="^/docs/.*"),
                event_filter(operator=PropertyOperator.NOT_REGEX, value="^/api/.*"),
                False,
            ),
            (
                "bool_value_vs_string_value",
                event_filter(operator=PropertyOperator.EXACT, value=True),
                event_filter(operator=PropertyOperator.IS_NOT, value="true"),
                True,
            ),
            (
                "number_value_vs_string_value",
                event_filter(operator=PropertyOperator.EXACT, value=1),
                event_filter(operator=PropertyOperator.IS_NOT, value="1"),
                True,
            ),
            (
                "different_keys",
                event_filter(key="utm_medium", operator=PropertyOperator.EXACT, value="abc"),
                event_filter(key="utm_source", operator=PropertyOperator.IS_NOT, value="abc"),
                False,
            ),
            (
                "different_filter_types",
                EventPropertyFilter(key="utm_medium", operator=PropertyOperator.EXACT, value="abc"),
                PersonPropertyFilter(key="utm_medium", operator=PropertyOperator.IS_NOT, value="abc"),
                False,
            ),
            (
                "different_group_type_indexes",
                GroupPropertyFilter(key="name", operator=PropertyOperator.EXACT, value="abc", group_type_index=0),
                GroupPropertyFilter(key="name", operator=PropertyOperator.IS_NOT, value="abc", group_type_index=1),
                False,
            ),
            (
                "same_group_type_index",
                GroupPropertyFilter(key="name", operator=PropertyOperator.EXACT, value="abc", group_type_index=0),
                GroupPropertyFilter(key="name", operator=PropertyOperator.IS_NOT, value="abc", group_type_index=0),
                True,
            ),
            (
                "numeric_range_operators_out_of_scope",
                event_filter(operator=PropertyOperator.GT, value=10),
                event_filter(operator=PropertyOperator.LT, value=5),
                False,
            ),
            (
                "cohort_filters_skipped",
                CohortPropertyFilter(key="id", value=1),
                CohortPropertyFilter(key="id", value=2),
                False,
            ),
            (
                "hogql_filters_skipped",
                HogQLPropertyFilter(key="properties.utm_medium = 'abc'"),
                HogQLPropertyFilter(key="properties.utm_medium != 'abc'"),
                False,
            ),
            (
                "empty_list_value_is_noop",
                event_filter(operator=PropertyOperator.EXACT, value=[]),
                event_filter(operator=PropertyOperator.IS_NOT, value=[]),
                False,
            ),
            (
                "none_value_exact_vs_is_not_set_is_noop",
                event_filter(operator=PropertyOperator.EXACT, value=None),
                event_filter(operator=PropertyOperator.IS_NOT_SET),
                False,
            ),
            (
                "missing_operator_defaults_to_exact",
                EventPropertyFilter(key="utm_medium", value="abc"),
                event_filter(operator=PropertyOperator.IS_NOT, value="abc"),
                True,
            ),
        ]
    )
    def test_contradiction_matrix(self, _name, insight_filter, dashboard_filter, expect_conflict):
        surviving, conflicts = drop_conflicting_insight_filters([insight_filter], [dashboard_filter])

        if expect_conflict:
            assert surviving == []
            assert len(conflicts) == 1
            assert conflicts[0].insight_filter == insight_filter
            assert conflicts[0].dashboard_filter == dashboard_filter
        else:
            assert surviving == [insight_filter]
            assert conflicts == []

    def test_only_contradicted_filters_are_dropped(self):
        contradicted = event_filter(key="utm_medium", operator=PropertyOperator.EXACT, value="abc")
        compatible = event_filter(key="utm_source", operator=PropertyOperator.EXACT, value="google")
        dashboard = event_filter(key="utm_medium", operator=PropertyOperator.IS_NOT, value="abc")

        surviving, conflicts = drop_conflicting_insight_filters([contradicted, compatible], [dashboard])

        assert surviving == [compatible]
        assert surviving[0] is compatible
        assert len(conflicts) == 1
        assert conflicts[0].insight_filter == contradicted
        assert conflicts[0].dashboard_filter == dashboard
