from datetime import datetime
from typing import Any

from freezegun import freeze_time

from posthog.schema import (
    AssistantDateRange,
    AssistantFunnelsEventsNode,
    AssistantFunnelsFilter,
    AssistantFunnelsQuery,
    AssistantRetentionEventsNode,
    AssistantRetentionFilter,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
    Compare,
    FunnelStepReference,
    FunnelVizType,
)
from posthog.test.base import BaseTest

from ..format import (
    FunnelResultsFormatter,
    RetentionResultsFormatter,
    TrendsResultsFormatter,
    _format_duration,
    _format_number,
    _strip_datetime_seconds,
)


class TestFormatHelpers(BaseTest):
    def test_format_number(self):
        self.assertEqual(_format_number(1), "1")
        self.assertEqual(_format_number(1.0), "1")
        self.assertEqual(_format_number(1.1), "1.1")
        self.assertEqual(_format_number(1.123456789), "1.12346")
        self.assertEqual(_format_number(1.10000), "1.1")

    def test_format_duration(self):
        self.assertEqual(_format_duration(3661), "1h 1m 1s")
        self.assertEqual(_format_duration(0.5), "500ms")
        self.assertEqual(_format_duration(45, seconds_precision=2), "45s")
        self.assertEqual(_format_duration(90000, max_units=2), "1d 1h")


class TestCompression(BaseTest):
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

    def test_funnels_single_series(self):
        results: list[dict[str, Any]] = [
            {
                "action_id": "$pageview",
                "name": "$pageview",
                "custom_name": "custom",
                "order": 0,
                "people": [],
                "count": 5,
                "type": "events",
                "average_conversion_time": None,
                "median_conversion_time": None,
            },
            {
                "action_id": "$pageview",
                "name": "$pageview",
                "custom_name": None,
                "order": 1,
                "people": [],
                "count": 2,
                "type": "events",
                "average_conversion_time": 10,
                "median_conversion_time": 11,
            },
            {
                "action_id": "$pageview",
                "name": "$pageview",
                "custom_name": None,
                "order": 2,
                "people": [],
                "count": 1,
                "type": "events",
                "average_conversion_time": 20,
                "median_conversion_time": 22,
            },
        ]
        self.assertIn(
            "Metric|$pageview custom|$pageview|$pageview\nTotal person count|5|2|1\nConversion rate|100%|40%|20%\nDropoff rate|0%|60%|80%\nAverage conversion time|-|10s|20s\nMedian conversion time|-|11s|22s",
            FunnelResultsFormatter(AssistantFunnelsQuery(series=[]), results, self.team, datetime.now()).format(),
        )
        self.assertIn(
            "Metric|$pageview custom|$pageview|$pageview\nTotal person count|5|2|1\nConversion rate|100%|40%|50%\nDropoff rate|0%|60%|50%\nAverage conversion time|-|10s|20s\nMedian conversion time|-|11s|22s",
            FunnelResultsFormatter(
                AssistantFunnelsQuery(
                    series=[], funnelsFilter=AssistantFunnelsFilter(funnelStepReference=FunnelStepReference.PREVIOUS)
                ),
                results,
                self.team,
                datetime.now(),
            ).format(),
        )

    def test_funnels_with_zero_count(self):
        results: list[dict[str, Any]] = [
            {
                "action_id": "$pageview",
                "name": "$pageview",
                "custom_name": "custom",
                "order": 0,
                "people": [],
                "count": 0,
                "type": "events",
                "average_conversion_time": None,
                "median_conversion_time": None,
            },
            {
                "action_id": "$pageview",
                "name": "$pageview",
                "custom_name": None,
                "order": 1,
                "people": [],
                "count": 0,
                "type": "events",
                "average_conversion_time": None,
                "median_conversion_time": None,
            },
        ]
        self.assertIn(
            "Metric|$pageview custom|$pageview\nTotal person count|0|0\nConversion rate|100%|0%\nDropoff rate|0%|100%\nAverage conversion time|-|-\nMedian conversion time|-|-",
            FunnelResultsFormatter(AssistantFunnelsQuery(series=[]), results, self.team, datetime.now()).format(),
        )
        self.assertIn(
            "Metric|$pageview custom|$pageview\nTotal person count|0|0\nConversion rate|100%|0%\nDropoff rate|0%|100%\nAverage conversion time|-|-\nMedian conversion time|-|-",
            FunnelResultsFormatter(
                AssistantFunnelsQuery(
                    series=[], funnelsFilter=AssistantFunnelsFilter(funnelStepReference=FunnelStepReference.PREVIOUS)
                ),
                results,
                self.team,
                datetime.now(),
            ).format(),
        )

    def test_funnels_breakdown(self):
        results = [
            {
                "action_id": "$pageview",
                "name": "$pageview",
                "order": 0,
                "people": [],
                "count": 5,
                "type": "events",
                "average_conversion_time": None,
                "median_conversion_time": None,
                "breakdown_value": ["au"],
            },
            {
                "action_id": "signup",
                "name": "signup",
                "order": 1,
                "people": [],
                "count": 2,
                "type": "events",
                "average_conversion_time": 10,
                "median_conversion_time": 11,
                "breakdown_value": ["au"],
            },
        ]
        self.assertIn(
            "---au\nMetric|$pageview|signup\nTotal person count|5|2\nConversion rate|100%|40%\nDropoff rate|0%|60%\nAverage conversion time|-|10s\nMedian conversion time|-|11s",
            FunnelResultsFormatter(AssistantFunnelsQuery(series=[]), results, self.team, datetime.now()).format(),
        )

    def test_funnel_format_multiple_series(self):
        results = [
            [
                {
                    "action_id": "$pageview",
                    "name": "$pageview",
                    "order": 0,
                    "people": [],
                    "count": 5,
                    "type": "events",
                    "average_conversion_time": None,
                    "median_conversion_time": None,
                    "breakdown_value": ["au"],
                },
                {
                    "action_id": "signup",
                    "name": "signup",
                    "order": 1,
                    "people": [],
                    "count": 2,
                    "type": "events",
                    "average_conversion_time": 10,
                    "median_conversion_time": 11,
                    "breakdown_value": ["au"],
                },
            ],
            [
                {
                    "action_id": "$pageview",
                    "name": "$pageview",
                    "order": 0,
                    "people": [],
                    "count": 5,
                    "type": "events",
                    "average_conversion_time": None,
                    "median_conversion_time": None,
                    "breakdown_value": ["us"],
                },
                {
                    "action_id": "signup",
                    "name": "signup",
                    "order": 1,
                    "people": [],
                    "count": 2,
                    "type": "events",
                    "average_conversion_time": 10,
                    "median_conversion_time": 11,
                    "breakdown_value": ["us"],
                },
            ],
        ]

        with freeze_time("2025-02-07T15:00:00"):
            self.assertEqual(
                FunnelResultsFormatter(
                    AssistantFunnelsQuery(series=[]),
                    results,
                    self.team,
                    datetime.now(),
                ).format(),
                'Date range: 2025-01-31 00:00:00 to 2025-02-07 23:59:59\n\n---au\nMetric|$pageview|signup\nTotal person count|5|2\nConversion rate|100%|40%\nDropoff rate|0%|60%\nAverage conversion time|-|10s\nMedian conversion time|-|11s\n\n---us\nMetric|$pageview|signup\nTotal person count|5|2\nConversion rate|100%|40%\nDropoff rate|0%|60%\nAverage conversion time|-|10s\nMedian conversion time|-|11s\n\nConversion and drop-off rates are calculated in overall. For example, "Conversion rate: 9%" means that 9% of users from the first step completed the funnel.',
            )

    def test_format_date(self):
        self.assertEqual(_strip_datetime_seconds("2025-01-20"), "2025-01-20")
        self.assertEqual(_strip_datetime_seconds("2025-01-20 00:00:00"), "2025-01-20 00:00")
        self.assertEqual(_strip_datetime_seconds("2025-01-20 15:00"), "2025-01-20 15:00")

    def test_format_retention(self):
        results = [
            {
                "date": "2025-01-21T00:00:00-08:00",
                "label": "Day 0",
                "values": [{"count": 100}, {"count": 100}, {"count": 50}, {"count": 25}],
            },
            {
                "date": "2025-01-22T00:00:00-08:00",
                "label": "Day 1",
                "values": [{"count": 100}, {"count": 50}, {"count": 25}],
            },
            {
                "date": "2025-01-23T00:00:00-08:00",
                "label": "Day 2",
                "values": [{"count": 50}, {"count": 25}],
            },
            {"date": "2025-01-24T00:00:00-08:00", "label": "Day 3", "values": [{"count": 25}]},
        ]

        self.assertEqual(
            RetentionResultsFormatter(
                AssistantRetentionQuery(
                    retentionFilter=AssistantRetentionFilter(
                        targetEntity=AssistantRetentionEventsNode(name="event"),
                        returningEntity=AssistantRetentionEventsNode(name="event"),
                    )
                ),
                results,
            ).format(),
            "Date range: 2025-01-21 00:00 to 2025-01-24 00:00\n"
            "Time interval: Day\n"
            "Date|Number of persons on date|Day 0|Day 1|Day 2|Day 3\n"
            "2025-01-21 00:00|100|100%|100%|50%|25%\n"
            "2025-01-22 00:00|100|100%|50%|25%\n"
            "2025-01-23 00:00|50|100%|50%\n"
            "2025-01-24 00:00|25|100%",
        )

    def test_format_retention_with_zero_count(self):
        results = [
            {
                "date": "2025-01-21T00:00:00-08:00",
                "label": "Day 0",
                "values": [{"count": 0}, {"count": 0}, {"count": 0}, {"count": 0}],
            },
            {
                "date": "2025-01-22T00:00:00-08:00",
                "label": "Day 1",
                "values": [{"count": 0}, {"count": 0}, {"count": 0}],
            },
            {
                "date": "2025-01-23T00:00:00-08:00",
                "label": "Day 2",
                "values": [{"count": 0}, {"count": 0}],
            },
            {"date": "2025-01-24T00:00:00-08:00", "label": "Day 3", "values": [{"count": 0}]},
        ]

        self.assertEqual(
            RetentionResultsFormatter(
                AssistantRetentionQuery(
                    retentionFilter=AssistantRetentionFilter(
                        targetEntity=AssistantRetentionEventsNode(name="event"),
                        returningEntity=AssistantRetentionEventsNode(name="event"),
                    )
                ),
                results,
            ).format(),
            "Date range: 2025-01-21 00:00 to 2025-01-24 00:00\n"
            "Time interval: Day\n"
            "Date|Number of persons on date|Day 0|Day 1|Day 2|Day 3\n"
            "2025-01-21 00:00|0|100%|0%|0%|0%\n"
            "2025-01-22 00:00|0|100%|0%|0%\n"
            "2025-01-23 00:00|0|100%|0%\n"
            "2025-01-24 00:00|0|100%",
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

    def test_funnels_time_to_convert(self):
        query = AssistantFunnelsQuery(
            series=[
                AssistantFunnelsEventsNode(event="$pageview", custom_name="custom"),
                AssistantFunnelsEventsNode(event="$ai_trace"),
            ],
            dateRange=AssistantDateRange(date_from="2025-01-20", date_to="2025-01-22"),
            funnelsFilter=AssistantFunnelsFilter(funnelVizType=FunnelVizType.TIME_TO_CONVERT),
        )
        results = {"average_conversion_time": 600, "bins": [[600, 1], [601, 0]]}
        self.assertEqual(
            FunnelResultsFormatter(query, results, self.team, datetime.now()).format(),
            "Date range: 2025-01-20 00:00:00 to 2025-01-22 23:59:59\n\nEvents: $pageview (custom) -> $ai_trace\nAverage time to convert|User distribution\n10m|100%\n10m 1s|0%\n\nThe user distribution is the percentage of users who completed the funnel in the given period.",
        )

    def test_funnel_trends(self):
        results = [
            {
                "count": 31,
                "data": [10, 15.5, 0],
                "days": ["2025-01-08", "2025-01-09", "2025-01-10"],
                "labels": ["8-Jan-2025", "9-Jan-2025", "10-Jan-2025"],
            }
        ]
        query = AssistantFunnelsQuery(
            series=[
                AssistantFunnelsEventsNode(event="$pageview", custom_name="custom"),
                AssistantFunnelsEventsNode(event="$ai_trace"),
            ],
            dateRange=AssistantDateRange(date_from="2025-01-08", date_to="2025-01-10"),
            funnelsFilter=AssistantFunnelsFilter(funnelVizType=FunnelVizType.TRENDS),
        )
        self.assertEqual(
            FunnelResultsFormatter(query, results, self.team, datetime.now()).format(),
            "Date|$pageview (custom) -> $ai_trace conversion|$pageview (custom) -> $ai_trace drop-off\n2025-01-08|10%|90%\n2025-01-09|15.5%|84.5%\n2025-01-10|0%|100%",
        )

    def test_funnel_trends_with_breakdown(self):
        results = [
            {
                "count": 31,
                "data": [10, 15.5, 0],
                "days": ["2025-01-08", "2025-01-09", "2025-01-10"],
                "labels": ["8-Jan-2025", "9-Jan-2025", "10-Jan-2025"],
                "breakdown_value": ["au"],
            },
            {
                "count": 31,
                "data": [5, 25, 50],
                "days": ["2025-01-08", "2025-01-09", "2025-01-10"],
                "labels": ["8-Jan-2025", "9-Jan-2025", "10-Jan-2025"],
                "breakdown_value": ["us"],
            },
        ]
        query = AssistantFunnelsQuery(
            series=[
                AssistantFunnelsEventsNode(event="$pageview", custom_name="custom"),
                AssistantFunnelsEventsNode(event="$ai_trace"),
            ],
            dateRange=AssistantDateRange(date_from="2025-01-08", date_to="2025-01-10"),
            funnelsFilter=AssistantFunnelsFilter(funnelVizType=FunnelVizType.TRENDS),
        )

        self.assertEqual(
            FunnelResultsFormatter(query, results, self.team, datetime.now()).format(),
            "Date|$pageview (custom) -> $ai_trace au breakdown conversion|$pageview (custom) -> $ai_trace au breakdown drop-off|$pageview (custom) -> $ai_trace us breakdown conversion|$pageview (custom) -> $ai_trace us breakdown drop-off\n2025-01-08|10%|90%|5%|95%\n2025-01-09|15.5%|84.5%|25%|75%\n2025-01-10|0%|100%|50%|50%",
        )
