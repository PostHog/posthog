from unittest import TestCase

from parameterized import parameterized

from .. import LifecycleResultsFormatter


class TestLifecycleResultsFormatter(TestCase):
    @parameterized.expand(
        [
            (
                "all_statuses",
                [
                    {
                        "data": [46.0, 38.0],
                        "days": ["2025-01-20", "2025-01-21"],
                        "labels": ["20-Jan-2025", "21-Jan-2025"],
                        "label": "$pageview - new",
                        "status": "new",
                        "action": {"order": 0, "type": "events", "name": "$pageview", "id": "$pageview"},
                    },
                    {
                        "data": [120.0, 105.0],
                        "days": ["2025-01-20", "2025-01-21"],
                        "labels": ["20-Jan-2025", "21-Jan-2025"],
                        "label": "$pageview - returning",
                        "status": "returning",
                        "action": {"order": 0, "type": "events", "name": "$pageview", "id": "$pageview"},
                    },
                    {
                        "data": [15.0, 22.0],
                        "days": ["2025-01-20", "2025-01-21"],
                        "labels": ["20-Jan-2025", "21-Jan-2025"],
                        "label": "$pageview - resurrecting",
                        "status": "resurrecting",
                        "action": {"order": 0, "type": "events", "name": "$pageview", "id": "$pageview"},
                    },
                    {
                        "data": [-30.0, -45.0],
                        "days": ["2025-01-20", "2025-01-21"],
                        "labels": ["20-Jan-2025", "21-Jan-2025"],
                        "label": "$pageview - dormant",
                        "status": "dormant",
                        "action": {"order": 0, "type": "events", "name": "$pageview", "id": "$pageview"},
                    },
                ],
                "Date|new|returning|resurrecting|dormant\n2025-01-20|46|120|15|-30\n2025-01-21|38|105|22|-45",
            ),
            (
                "empty_results",
                [],
                "No data recorded for this time period.",
            ),
            (
                "partial_statuses",
                [
                    {
                        "data": [10.0, 20.0],
                        "days": ["2025-01-20", "2025-01-21"],
                        "labels": ["20-Jan-2025", "21-Jan-2025"],
                        "label": "$pageview - new",
                        "status": "new",
                        "action": {"order": 0, "type": "events", "name": "$pageview", "id": "$pageview"},
                    },
                    {
                        "data": [50.0, 60.0],
                        "days": ["2025-01-20", "2025-01-21"],
                        "labels": ["20-Jan-2025", "21-Jan-2025"],
                        "label": "$pageview - returning",
                        "status": "returning",
                        "action": {"order": 0, "type": "events", "name": "$pageview", "id": "$pageview"},
                    },
                ],
                "Date|new|returning\n2025-01-20|10|50\n2025-01-21|20|60",
            ),
        ]
    )
    def test_lifecycle_format(self, _name: str, results: list, expected: str):
        self.assertEqual(LifecycleResultsFormatter(results).format(), expected)
