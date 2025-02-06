from posthog.schema import Compare, FunnelStepReference
from posthog.test.base import BaseTest

from ..format import (
    _extract_series_label,
    _format_duration,
    _format_funnels_results,
    _format_number,
    _strip_datetime_seconds,
    compress_and_format_funnels_results,
    compress_and_format_retention_results,
    compress_and_format_trends_results,
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
            compress_and_format_trends_results(results),
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
            compress_and_format_trends_results(results),
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
            compress_and_format_trends_results(results),
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
            compress_and_format_trends_results(results),
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

        self.assertEqual(_extract_series_label(series), "Custom Name (breakdown)")
        series.pop("action")
        self.assertEqual(_extract_series_label(series), "$pageview (breakdown)")

    def test_funnels_single_series(self):
        results = [
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
        self.assertEqual(
            _format_funnels_results(results, FunnelStepReference.TOTAL),
            "Metric|$pageview custom|$pageview|$pageview\nTotal person count|5|2|1\nConversion rate|100%|40%|20%\nDropoff rate|0%|60%|80%\nAverage conversion time|-|10s|20s\nMedian conversion time|-|11s|22s",
        )
        self.assertEqual(
            _format_funnels_results(results, FunnelStepReference.PREVIOUS),
            "Metric|$pageview custom|$pageview|$pageview\nTotal person count|5|2|1\nConversion rate|100%|40%|50%\nDropoff rate|0%|60%|50%\nAverage conversion time|-|10s|20s\nMedian conversion time|-|11s|22s",
        )

    def test_funnels_with_zero_count(self):
        results = [
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
        self.assertEqual(
            _format_funnels_results(results, FunnelStepReference.TOTAL),
            "Metric|$pageview custom|$pageview\nTotal person count|0|0\nConversion rate|100%|0%\nDropoff rate|0%|100%\nAverage conversion time|-|-\nMedian conversion time|-|-",
        )
        self.assertEqual(
            _format_funnels_results(results, FunnelStepReference.PREVIOUS),
            "Metric|$pageview custom|$pageview\nTotal person count|0|0\nConversion rate|100%|0%\nDropoff rate|0%|100%\nAverage conversion time|-|-\nMedian conversion time|-|-",
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
        self.assertEqual(
            _format_funnels_results(results, FunnelStepReference.TOTAL),
            "---au\nMetric|$pageview|signup\nTotal person count|5|2\nConversion rate|100%|40%\nDropoff rate|0%|60%\nAverage conversion time|-|10s\nMedian conversion time|-|11s",
        )

    def test_format_multiple_series(self):
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

        self.assertIn(
            "Date range: 2025-01-20 to 2025-01-22\n\n---au\nMetric|$pageview|signup\nTotal person count|5|2\nConversion rate|100%|40%\nDropoff rate|0%|60%\nAverage conversion time|-|10s\nMedian conversion time|-|11s\n\n---us\nMetric|$pageview|signup\nTotal person count|5|2\nConversion rate|100%|40%\nDropoff rate|0%|60%\nAverage conversion time|-|10s\nMedian conversion time|-|11s",
            compress_and_format_funnels_results(results, date_from="2025-01-20", date_to="2025-01-22"),
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
            compress_and_format_retention_results(results),
            "Date range: 2025-01-21 00:00 to 2025-01-24 00:00\n"
            "Granularity: Day\n"
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
            compress_and_format_retention_results(results),
            "Date range: 2025-01-21 00:00 to 2025-01-24 00:00\n"
            "Granularity: Day\n"
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
            compress_and_format_trends_results(results),
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
            compress_and_format_trends_results(results),
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
            compress_and_format_trends_results(results),
            "Previous period:\nDate range|Aggregated value for $pageview\n2025-01-17 to 2025-01-19|993\n\nCurrent period:\nDate range|Aggregated value for $pageview\n2025-01-20 to 2025-01-22|1000",
        )
