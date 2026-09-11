from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import AssistantTrendsEventsNode, AssistantTrendsFilter, AssistantTrendsQuery, TrendsFormulaNode

from ee.hogai.chat_agent.trends.quality import find_trends_quality_issues


class TestFindTrendsQualityIssues(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "property_math_without_math_property",
                AssistantTrendsQuery(series=[AssistantTrendsEventsNode(event="$pageview", math="avg")]),
                "math_property",
            ),
            (
                "hogql_math_without_expression",
                AssistantTrendsQuery(series=[AssistantTrendsEventsNode(event="$pageview", math="hogql")]),
                "math_hogql",
            ),
            (
                "group_math_without_index",
                AssistantTrendsQuery(series=[AssistantTrendsEventsNode(event="$pageview", math="unique_group")]),
                "math_group_type_index",
            ),
            (
                "property_math_with_blank_math_property",
                AssistantTrendsQuery(
                    series=[AssistantTrendsEventsNode(event="$pageview", math="avg", math_property="   ")]
                ),
                "`math_property` is blank",
            ),
            (
                "hogql_math_with_blank_expression",
                AssistantTrendsQuery(
                    series=[AssistantTrendsEventsNode(event="$pageview", math="hogql", math_hogql="")]
                ),
                "`math_hogql` is blank",
            ),
            (
                "seconds_property_formatted_as_milliseconds",
                AssistantTrendsQuery(
                    series=[
                        AssistantTrendsEventsNode(event="$pageview", math="avg", math_property="$session_duration")
                    ],
                    trendsFilter=AssistantTrendsFilter(aggregationAxisFormat="duration_ms"),
                ),
                "wrong unit",
            ),
            (
                "seconds_property_labeled_with_minutes",
                AssistantTrendsQuery(
                    series=[
                        AssistantTrendsEventsNode(event="$pageview", math="avg", math_property="$session_duration")
                    ],
                    trendsFilter=AssistantTrendsFilter(
                        aggregationAxisFormat="numeric", aggregationAxisPostfix=" minutes"
                    ),
                ),
                "another time unit",
            ),
            (
                "count_formatted_as_duration",
                AssistantTrendsQuery(
                    series=[AssistantTrendsEventsNode(event="$pageview", math="dau")],
                    trendsFilter=AssistantTrendsFilter(aggregationAxisFormat="duration"),
                ),
                "No series produces a length of time",
            ),
            (
                "formula_references_undefined_series",
                AssistantTrendsQuery(
                    series=[AssistantTrendsEventsNode(event="$pageview", math="total")],
                    trendsFilter=AssistantTrendsFilter(formulaNodes=[TrendsFormulaNode(formula="A/B")]),
                ),
                "references series B",
            ),
            (
                "formula_aggregates_a_series",
                AssistantTrendsQuery(
                    series=[AssistantTrendsEventsNode(event="$pageview", math="total")],
                    trendsFilter=AssistantTrendsFilter(formulaNodes=[TrendsFormulaNode(formula="avg(A)")]),
                ),
                "fails to run",
            ),
            (
                "count_property_formatted_as_duration",
                AssistantTrendsQuery(
                    series=[AssistantTrendsEventsNode(event="$pageview", math="avg", math_property="$pageview_count")],
                    trendsFilter=AssistantTrendsFilter(aggregationAxisFormat="duration"),
                ),
                "No series produces a length of time",
            ),
            (
                "count_only_formula_formatted_as_duration",
                AssistantTrendsQuery(
                    series=[
                        AssistantTrendsEventsNode(event="$pageview", math="dau"),
                        AssistantTrendsEventsNode(event="$pageview", math="total"),
                    ],
                    trendsFilter=AssistantTrendsFilter(
                        aggregationAxisFormat="duration", formulaNodes=[TrendsFormulaNode(formula="A/B")]
                    ),
                ),
                "No series produces a length of time",
            ),
            ("no_series", AssistantTrendsQuery(series=[]), "no series"),
        ]
    )
    def test_reports_query_that_answers_with_a_wrong_number(self, _name, query, expected_fragment):
        issues = find_trends_quality_issues(query)
        self.assertEqual(len(issues), 1, issues)
        self.assertIn(expected_fragment, issues[0])

    @parameterized.expand(
        [
            (
                "count_of_events",
                AssistantTrendsQuery(series=[AssistantTrendsEventsNode(event="$pageview", math="total")]),
            ),
            (
                "seconds_property_formatted_as_duration",
                AssistantTrendsQuery(
                    series=[
                        AssistantTrendsEventsNode(event="$pageview", math="avg", math_property="$session_duration")
                    ],
                    trendsFilter=AssistantTrendsFilter(aggregationAxisFormat="duration"),
                ),
            ),
            (
                "milliseconds_property_formatted_as_milliseconds",
                AssistantTrendsQuery(
                    series=[AssistantTrendsEventsNode(event="$pageview", math="p95", math_property="load_time_ms")],
                    trendsFilter=AssistantTrendsFilter(aggregationAxisFormat="duration_ms"),
                ),
            ),
            (
                "group_math_with_index",
                AssistantTrendsQuery(
                    series=[AssistantTrendsEventsNode(event="$pageview", math="unique_group", math_group_type_index=0)]
                ),
            ),
            (
                "formula_over_defined_series",
                AssistantTrendsQuery(
                    series=[
                        AssistantTrendsEventsNode(event="$pageview", math="dau"),
                        AssistantTrendsEventsNode(event="$pageview", math="total"),
                    ],
                    trendsFilter=AssistantTrendsFilter(
                        aggregationAxisFormat="percentage_scaled", formulaNodes=[TrendsFormulaNode(formula="A/B")]
                    ),
                ),
            ),
            (
                "formula_over_a_seconds_property_formatted_as_duration",
                AssistantTrendsQuery(
                    series=[
                        AssistantTrendsEventsNode(event="$pageview", math="sum", math_property="$session_duration"),
                        AssistantTrendsEventsNode(event="$pageview", math="dau"),
                    ],
                    trendsFilter=AssistantTrendsFilter(
                        aggregationAxisFormat="duration", formulaNodes=[TrendsFormulaNode(formula="A/B")]
                    ),
                ),
            ),
        ]
    )
    def test_passes_sound_query(self, _name, query):
        self.assertEqual(find_trends_quality_issues(query), [])
