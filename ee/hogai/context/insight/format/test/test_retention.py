from posthog.test.base import BaseTest

from posthog.schema import AssistantRetentionEventsNode, AssistantRetentionFilter, AssistantRetentionQuery

from .. import RetentionResultsFormatter


class TestRetentionResultsFormatter(BaseTest):
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
