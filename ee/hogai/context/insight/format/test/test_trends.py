from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import (
    AssistantDateRange,
    AssistantTrendsActionsNode,
    AssistantTrendsEventsNode,
    AssistantTrendsFilter,
    AssistantTrendsQuery,
    Compare,
    IntervalType,
    TrendsFormulaNode,
)

from .. import TrendsResultsFormatter


class TestTrendsResultsFormatter(BaseTest):
    def test_trends_single_series(self):
        results = [
            {
                "data": [242, 46, 0],
                "labels": ["23-Jan-2025", "24-Jan-2025", "25-Jan-2025"],
                "days": ["2025-01-23", "2025-01-24", "2025-01-25"],
                "count": 288,
                "label": "$pageview",
                "order": 0,
            }
        ]

        self.assertEqual(
            TrendsResultsFormatter(AssistantTrendsQuery(series=[]), results).format(),
            "Date|$pageview\n2025-01-23|242\n2025-01-24|46\n2025-01-25|0",
        )

    def test_trends_multiple_series(self):
        results = [
            {
                "data": [242, 46, 0],
                "labels": ["23-Jan-2025", "24-Jan-2025", "25-Jan-2025"],
                "days": ["2025-01-23", "2025-01-24", "2025-01-25"],
                "count": 288,
                "label": "$pageview1",
            },
            {
                "data": [46, 0, 242],
                "labels": ["23-Jan-2025", "24-Jan-2025", "25-Jan-2025"],
                "days": ["2025-01-23", "2025-01-24", "2025-01-25"],
                "count": 288,
                "label": "$pageview2",
            },
        ]

        self.assertEqual(
            TrendsResultsFormatter(AssistantTrendsQuery(series=[]), results).format(),
            "Date|$pageview1|$pageview2\n2025-01-23|242|46\n2025-01-24|46|0\n2025-01-25|0|242",
        )

    def test_trends_comparison(self):
        results = [
            {
                "data": [242, 46, 0],
                "labels": ["20-Jan-2025", "21-Jan-2025", "22-Jan-2025"],
                "days": ["2025-01-20", "2025-01-21", "2025-01-22"],
                "count": 288,
                "label": "$pageview",
                "compare": True,
                "compare_label": Compare.PREVIOUS,
            },
            {
                "data": [46, 0, 242],
                "labels": ["23-Jan-2025", "24-Jan-2025", "25-Jan-2025"],
                "days": ["2025-01-23", "2025-01-24", "2025-01-25"],
                "count": 288,
                "label": "$pageview",
                "compare_label": Compare.CURRENT,
            },
        ]

        self.assertEqual(
            TrendsResultsFormatter(AssistantTrendsQuery(series=[]), results).format(),
            "Previous period:\nDate|$pageview\n2025-01-20|242\n2025-01-21|46\n2025-01-22|0\n\nCurrent period:\nDate|$pageview\n2025-01-23|46\n2025-01-24|0\n2025-01-25|242",
        )

    def test_trends_empty_series(self):
        results = [
            {
                "data": [242, 46, 0],
                "labels": ["20-Jan-2025", "21-Jan-2025", "22-Jan-2025"],
                "days": ["2025-01-20", "2025-01-21", "2025-01-22"],
                "count": 288,
                "label": "$pageview",
                "compare": True,
                "compare_label": Compare.CURRENT,
            },
        ]

        self.assertEqual(
            TrendsResultsFormatter(AssistantTrendsQuery(series=[]), results).format(),
            "Date|$pageview\n2025-01-20|242\n2025-01-21|46\n2025-01-22|0",
        )

    @parameterized.expand(
        [
            (
                "breakdown_with_custom_name",
                AssistantTrendsQuery(series=[AssistantTrendsEventsNode(event="$pageview", custom_name="Views")]),
                [{"label": "Chrome", "order": 0, "breakdown_value": "Chrome"}],
                None,
                "Date|Views breakdown for the value `Chrome`",
            ),
            (
                "breakdown_without_rename",
                AssistantTrendsQuery(series=[AssistantTrendsEventsNode(event="$pageview", name="$pageview")]),
                [{"label": "Chrome", "order": 0, "breakdown_value": "Chrome"}],
                None,
                "Date|Chrome breakdown for the value `Chrome`",
            ),
            (
                "each_row_takes_the_series_at_its_order",
                AssistantTrendsQuery(
                    series=[
                        AssistantTrendsEventsNode(event="$pageview", name="$pageview"),
                        AssistantTrendsEventsNode(event="sign up", name="Registrations"),
                    ]
                ),
                [{"label": "$pageview", "order": 0}, {"label": "sign up", "order": 1}],
                None,
                "Date|$pageview|Registrations",
            ),
            (
                "an_action_keeps_the_name_it_was_saved_with",
                AssistantTrendsQuery(series=[AssistantTrendsActionsNode(id=7, name="Old purchase name")]),
                [{"label": "Purchase made", "order": 0}],
                {7: "Purchase made"},
                "Date|Old purchase name",
            ),
            (
                "formula_rows_take_no_series_name",
                AssistantTrendsQuery(
                    series=[
                        AssistantTrendsEventsNode(event="$pageview", custom_name="Views"),
                        AssistantTrendsEventsNode(event="sign up", custom_name="Registrations"),
                    ],
                    trendsFilter=AssistantTrendsFilter(
                        formulaNodes=[TrendsFormulaNode(formula="A+B"), TrendsFormulaNode(formula="A-B")]
                    ),
                ),
                [{"label": "Formula (A+B)", "order": 0}, {"label": "Formula (A-B)", "order": 1}],
                None,
                "Date|Formula (A+B)|Formula (A-B)",
            ),
        ]
    )
    def test_trends_series_label(self, _name, query, rows, action_names, expected_header):
        results = [{"data": [1], "labels": ["20-Jan-2025"], "days": ["2025-01-20"], **row} for row in rows]

        formatted = TrendsResultsFormatter(query, results, action_names=action_names).format()

        self.assertEqual(formatted.split("\n")[0], expected_header)

    def test_trends_marks_partial_current_and_future_buckets(self):
        # now is midday on the 25th (UTC), so the 25th's bucket is still collecting and the 26th is
        # in the future — both must be flagged so daily automation doesn't treat them as complete.
        results = [
            {
                "data": [242, 46, 0],
                "days": ["2025-01-24", "2025-01-25", "2025-01-26"],
                "count": 288,
                "label": "$pageview",
            }
        ]
        self.assertEqual(
            TrendsResultsFormatter(
                AssistantTrendsQuery(series=[]),
                results,
                self.team,
                datetime(2025, 1, 25, 12, 0, 0, tzinfo=UTC),
            ).format(),
            "Date|$pageview\n2025-01-24|242\n2025-01-25 (partial)|46\n2025-01-26 (partial)|0\n\n"
            'Note: rows marked "(partial)" cover an interval that is still in progress as of the query time, '
            "so their values are incomplete. Timezone: UTC.",
        )

    def test_trends_does_not_mark_complete_buckets(self):
        # Every bucket ends before now, so nothing is partial and no note is appended.
        results = [
            {
                "data": [242, 46, 0],
                "days": ["2025-01-23", "2025-01-24", "2025-01-25"],
                "count": 288,
                "label": "$pageview",
            }
        ]
        self.assertEqual(
            TrendsResultsFormatter(
                AssistantTrendsQuery(
                    series=[], dateRange=AssistantDateRange(date_from="2025-01-23", date_to="2025-01-25")
                ),
                results,
                self.team,
                datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC),
            ).format(),
            "Date|$pageview\n2025-01-23|242\n2025-01-24|46\n2025-01-25|0",
        )

    def test_trends_marks_partial_hourly_bucket(self):
        # Hourly granularity: only the in-progress hour (and later) is partial.
        results = [
            {
                "data": [5, 9, 0],
                "days": ["2025-01-25 10:00:00", "2025-01-25 11:00:00", "2025-01-25 12:00:00"],
                "count": 14,
                "label": "$pageview",
            }
        ]
        self.assertEqual(
            TrendsResultsFormatter(
                AssistantTrendsQuery(series=[], interval=IntervalType.HOUR),
                results,
                self.team,
                datetime(2025, 1, 25, 12, 30, 0, tzinfo=UTC),
            ).format(),
            "Date|$pageview\n2025-01-25 10:00|5\n2025-01-25 11:00|9\n2025-01-25 12:00 (partial)|0\n\n"
            'Note: rows marked "(partial)" cover an interval that is still in progress as of the query time, '
            "so their values are incomplete. Timezone: UTC.",
        )

    def test_trends_labelless_series(self):
        # A series with no label, custom_name, or breakdown_value used to crash the formatter with
        # `AttributeError: 'NoneType' object has no attribute 'replace'`. It should render as an
        # empty label instead.
        results = [
            {
                "data": [242, 46, 0],
                "labels": ["23-Jan-2025", "24-Jan-2025", "25-Jan-2025"],
                "days": ["2025-01-23", "2025-01-24", "2025-01-25"],
                "count": 288,
                "label": None,
            }
        ]

        self.assertEqual(
            TrendsResultsFormatter(AssistantTrendsQuery(series=[]), results).format(),
            "Date|\n2025-01-23|242\n2025-01-24|46\n2025-01-25|0",
        )

    def test_trends_aggregated_value(self):
        results = [
            {
                "data": [],
                "days": [],
                "count": 0,
                "aggregated_value": 993,
                "label": "$pageview",
            }
        ]
        self.assertEqual(
            TrendsResultsFormatter(AssistantTrendsQuery(series=[]), results).format(),
            "Date range|Aggregated value for $pageview\nAll time|993",
        )

    @parameterized.expand(
        [
            (
                "iso_strings_crossing_local_midnight",
                {"date_from": "2026-10-12T23:41:45-07:00", "date_to": "2026-10-13T00:41:49-07:00"},
                "2026-10-12 23:41:45-07:00 to 2026-10-13 00:41:49-07:00",
            ),
            (
                "datetimes_with_microseconds",
                {
                    "date_from": datetime(2026, 10, 12, 23, 41, 45, 123456, tzinfo=ZoneInfo("America/Los_Angeles")),
                    "date_to": datetime(2026, 10, 13, 0, 41, 49, 999999, tzinfo=ZoneInfo("America/Los_Angeles")),
                },
                "2026-10-12 23:41:45-07:00 to 2026-10-13 00:41:49-07:00",
            ),
        ]
    )
    def test_trends_aggregated_value_uses_resolved_date_range(self, _name, resolved_date_range, expected_range):
        results = [
            {
                "data": [],
                "days": [],
                "count": 0,
                "aggregated_value": 82,
                "label": "$pageview",
            }
        ]
        self.assertEqual(
            TrendsResultsFormatter(
                AssistantTrendsQuery(series=[]), results, resolved_date_range=resolved_date_range
            ).format(),
            f"Date range|Aggregated value for $pageview\n{expected_range}|82",
        )

    def test_trends_aggregated_values(self):
        results = [
            {
                "data": [],
                "days": [],
                "count": 0,
                "aggregated_value": 993,
                "label": "$pageview",
            },
            {
                "data": [],
                "days": [],
                "count": 0,
                "aggregated_value": 1000,
                "label": "$pageleave",
            },
        ]
        self.assertEqual(
            TrendsResultsFormatter(AssistantTrendsQuery(series=[]), results).format(),
            "Date range|Aggregated value for $pageview|Aggregated value for $pageleave\nAll time|993|1000",
        )

    @parameterized.expand(
        [
            (
                "aggregated_series_first",
                [
                    {
                        "data": [],
                        "days": [],
                        "count": 0,
                        "aggregated_value": 993,
                        "label": "$pageview",
                    },
                    {
                        "data": [],
                        "days": [],
                        "count": 0,
                        "label": "$pageleave",
                    },
                ],
                "Date range|Aggregated value for $pageview|Aggregated value for $pageleave\nAll time|993|N/A",
            ),
            (
                "aggregated_series_second",
                [
                    {
                        "data": [],
                        "days": [],
                        "count": 0,
                        "label": "$pageleave",
                    },
                    {
                        "data": [],
                        "days": [],
                        "count": 0,
                        "aggregated_value": 993,
                        "label": "$pageview",
                    },
                ],
                "Date range|Aggregated value for $pageleave|Aggregated value for $pageview\nAll time|N/A|993",
            ),
        ]
    )
    def test_trends_aggregated_values_with_mixed_series(self, _name, results, expected):
        self.assertEqual(
            TrendsResultsFormatter(AssistantTrendsQuery(series=[]), results).format(),
            expected,
        )

    def test_trends_aggregated_value_with_null_action(self):
        results = [
            {
                "data": None,
                "days": [],
                "count": 0,
                "aggregated_value": 92.22,
                "label": "Bounce rate",
                "breakdown_value": ["/news-research"],
            }
        ]
        self.assertEqual(
            TrendsResultsFormatter(AssistantTrendsQuery(series=[]), results).format(),
            "Date range|Aggregated value for Bounce rate breakdown for the value `/news-research`\nAll time|92.22",
        )

    def test_trends_aggregated_values_with_comparison(self):
        results = [
            {
                "data": [],
                "days": [],
                "count": 0,
                "aggregated_value": 993,
                "label": "$pageview",
                "compare": True,
                "compare_label": Compare.PREVIOUS,
            },
            {
                "data": [],
                "days": [],
                "count": 0,
                "aggregated_value": 1000,
                "label": "$pageview",
                "compare": True,
                "compare_label": Compare.CURRENT,
            },
        ]
        self.assertEqual(
            TrendsResultsFormatter(
                AssistantTrendsQuery(series=[]),
                results,
                resolved_date_range={
                    "date_from": "2025-01-20T00:00:00-08:00",
                    "date_to": "2025-01-22T23:59:59.999999-08:00",
                },
                resolved_compare_date_range={
                    "date_from": datetime(2025, 1, 17, tzinfo=ZoneInfo("America/Los_Angeles")),
                    "date_to": datetime(2025, 1, 19, 23, 59, 59, 999999, tzinfo=ZoneInfo("America/Los_Angeles")),
                },
            ).format(),
            "Previous period:\nDate range|Aggregated value for $pageview\n2025-01-17 00:00:00-08:00 to 2025-01-19 23:59:59-08:00|993\n\nCurrent period:\nDate range|Aggregated value for $pageview\n2025-01-20 00:00:00-08:00 to 2025-01-22 23:59:59-08:00|1000",
        )
