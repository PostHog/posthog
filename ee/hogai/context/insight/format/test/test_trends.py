from datetime import UTC, datetime

from posthog.test.base import BaseTest

from posthog.schema import AssistantDateRange, AssistantTrendsQuery, Compare, IntervalType

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
                "action": {
                    "days": ["2025-01-23T00:00:00+01:00", "2025-01-24T00:00:00+01:00", "2025-01-25T00:00:00+01:00"],
                    "id": "$pageview",
                    "type": "events",
                    "order": 0,
                    "name": "$pageview",
                    "custom_name": None,
                    "math": "total",
                    "math_property": None,
                    "math_hogql": None,
                    "math_group_type_index": None,
                    "properties": {},
                },
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

    def test_trends_breakdown_and_custom_name_label(self):
        series = {
            "data": [242, 46, 0],
            "labels": ["20-Jan-2025", "21-Jan-2025", "22-Jan-2025"],
            "days": ["2025-01-20", "2025-01-21", "2025-01-22"],
            "breakdown_value": 0,
            "label": "$pageview",
            "action": {
                "custom_name": "Custom Name",
            },
        }
        formatter = TrendsResultsFormatter(AssistantTrendsQuery(series=[]), [series])

        self.assertEqual(formatter._extract_series_label(series), "Custom Name breakdown for the value `0`")
        series.pop("action")
        self.assertEqual(formatter._extract_series_label(series), "$pageview breakdown for the value `0`")

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

    def test_trends_aggregated_value(self):
        results = [
            {
                "data": [],
                "days": [],
                "count": 0,
                "aggregated_value": 993,
                "label": "$pageview",
                "action": {
                    "days": ["2025-01-20", "2025-01-21", "2025-01-22"],
                },
            }
        ]
        self.assertEqual(
            TrendsResultsFormatter(AssistantTrendsQuery(series=[]), results).format(),
            "Date range|Aggregated value for $pageview\n2025-01-20 to 2025-01-22|993",
        )

    def test_trends_aggregated_values(self):
        results = [
            {
                "data": [],
                "days": [],
                "count": 0,
                "aggregated_value": 993,
                "label": "$pageview",
                "action": {
                    "days": ["2025-01-20", "2025-01-21", "2025-01-22"],
                },
            },
            {
                "data": [],
                "days": [],
                "count": 0,
                "aggregated_value": 1000,
                "label": "$pageleave",
                "action": {
                    "days": ["2025-01-20", "2025-01-21", "2025-01-22"],
                },
            },
        ]
        self.assertEqual(
            TrendsResultsFormatter(AssistantTrendsQuery(series=[]), results).format(),
            "Date range|Aggregated value for $pageview|Aggregated value for $pageleave\n2025-01-20 to 2025-01-22|993|1000",
        )

    def test_trends_aggregated_value_with_null_action(self):
        results = [
            {
                "data": None,
                "days": [],
                "count": 0,
                "aggregated_value": 92.22,
                "label": "Bounce rate",
                "action": None,
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
                "action": {
                    "days": ["2025-01-17", "2025-01-18", "2025-01-19"],
                },
                "compare": True,
                "compare_label": Compare.PREVIOUS,
            },
            {
                "data": [],
                "days": [],
                "count": 0,
                "aggregated_value": 1000,
                "label": "$pageview",
                "action": {
                    "days": ["2025-01-20", "2025-01-21", "2025-01-22"],
                },
                "compare": True,
                "compare_label": Compare.CURRENT,
            },
        ]
        self.assertEqual(
            TrendsResultsFormatter(AssistantTrendsQuery(series=[]), results).format(),
            "Previous period:\nDate range|Aggregated value for $pageview\n2025-01-17 to 2025-01-19|993\n\nCurrent period:\nDate range|Aggregated value for $pageview\n2025-01-20 to 2025-01-22|1000",
        )
