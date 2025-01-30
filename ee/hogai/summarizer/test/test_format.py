from ee.hogai.summarizer.format import _format_number, compress_and_format_trends_results
from posthog.schema import Compare
from posthog.test.base import BaseTest


class TestFormat(BaseTest):
    def test_format_number(self):
        self.assertEqual(_format_number(1), "1")
        self.assertEqual(_format_number(1.0), "1")
        self.assertEqual(_format_number(1.1), "1.1")
        self.assertEqual(_format_number(1.123456789), "1.12346")
        self.assertEqual(_format_number(1.123456789), "1.12346")
        self.assertEqual(_format_number(1.10000), "1.1")

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
