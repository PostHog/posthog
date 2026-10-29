from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import AssistantStickinessEventsNode, AssistantStickinessQuery

from .. import StickinessResultsFormatter


class TestStickinessResultsFormatter(SimpleTestCase):
    def test_stickiness_single_series(self):
        results = [
            {
                "count": 500,
                "data": [200, 150, 100, 50],
                "days": [1, 2, 3, 4],
                "labels": ["1 day", "2 days", "3 days", "4 days"],
                "label": "$pageview",
                "order": 0,
            }
        ]

        self.assertEqual(
            StickinessResultsFormatter(AssistantStickinessQuery(series=[]), results).format(),
            "Interval|$pageview\n1 day|200\n2 days|150\n3 days|100\n4 days|50",
        )

    def test_stickiness_multiple_series(self):
        results = [
            {
                "count": 500,
                "data": [200, 150, 100],
                "days": [1, 2, 3],
                "labels": ["1 day", "2 days", "3 days"],
                "label": "$pageview",
                "order": 0,
            },
            {
                "count": 300,
                "data": [100, 120, 80],
                "days": [1, 2, 3],
                "labels": ["1 day", "2 days", "3 days"],
                "label": "signup",
                "order": 1,
            },
        ]

        self.assertEqual(
            StickinessResultsFormatter(AssistantStickinessQuery(series=[]), results).format(),
            "Interval|$pageview|signup\n1 day|200|100\n2 days|150|120\n3 days|100|80",
        )

    def test_stickiness_comparison(self):
        results = [
            {
                "count": 400,
                "data": [200, 150, 50],
                "days": [1, 2, 3],
                "labels": ["1 day", "2 days", "3 days"],
                "label": "$pageview",
                "compare": True,
                "compare_label": "previous",
                "order": 0,
            },
            {
                "count": 500,
                "data": [250, 150, 100],
                "days": [1, 2, 3],
                "labels": ["1 day", "2 days", "3 days"],
                "label": "$pageview",
                "compare": True,
                "compare_label": "current",
                "order": 0,
            },
        ]

        self.assertEqual(
            StickinessResultsFormatter(AssistantStickinessQuery(series=[]), results).format(),
            "Previous period:\nInterval|$pageview\n1 day|200\n2 days|150\n3 days|50\n\nCurrent period:\nInterval|$pageview\n1 day|250\n2 days|150\n3 days|100",
        )

    def test_stickiness_empty_results(self):
        self.assertEqual(
            StickinessResultsFormatter(AssistantStickinessQuery(series=[]), []).format(),
            "No data recorded for this time period.",
        )

    @parameterized.expand(
        [
            ("custom_name", AssistantStickinessEventsNode(event="$pageview", custom_name="Page Views")),
            ("name_rename", AssistantStickinessEventsNode(event="$pageview", name="Page Views")),
        ]
    )
    def test_stickiness_renamed_series(self, _name, series):
        results = [
            {
                "count": 300,
                "data": [100, 120, 80],
                "days": [1, 2, 3],
                "labels": ["1 day", "2 days", "3 days"],
                "label": "$pageview",
                "order": 0,
            }
        ]

        self.assertEqual(
            StickinessResultsFormatter(AssistantStickinessQuery(series=[series]), results).format(),
            "Interval|Page Views\n1 day|100\n2 days|120\n3 days|80",
        )

    def test_stickiness_cumulative_labels(self):
        results = [
            {
                "count": 500,
                "data": [500, 300, 150],
                "days": [1, 2, 3],
                "labels": ["1 day or more", "2 days or more", "3 days or more"],
                "label": "$pageview",
                "order": 0,
            }
        ]

        self.assertEqual(
            StickinessResultsFormatter(AssistantStickinessQuery(series=[]), results).format(),
            "Interval|$pageview\n1 day or more|500\n2 days or more|300\n3 days or more|150",
        )
