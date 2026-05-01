from posthog.test.base import BaseTest

from posthog.schema import AssistantLifecycleEventsNode, AssistantLifecycleQuery, EventsNode, LifecycleQuery

from .. import LifecycleResultsFormatter


def _make_result(event_id, event_name, status, data, days, order=0, custom_name=None):
    return {
        "action": {
            "id": event_id,
            "type": "events",
            "order": order,
            "name": event_name,
            "custom_name": custom_name,
            "math": "total",
        },
        "label": f"{event_name} - {status}",
        "count": sum(data),
        "data": data,
        "labels": [f"label-{d}" for d in days],
        "days": days,
        "status": status,
    }


class TestLifecycleResultsFormatter(BaseTest):
    def test_format_single_series(self):
        results = [
            _make_result("$pageview", "$pageview", "new", [100, 80, 60], ["2025-01-01", "2025-01-02", "2025-01-03"]),
            _make_result(
                "$pageview", "$pageview", "returning", [50, 40, 30], ["2025-01-01", "2025-01-02", "2025-01-03"]
            ),
            _make_result(
                "$pageview", "$pageview", "resurrecting", [10, 8, 6], ["2025-01-01", "2025-01-02", "2025-01-03"]
            ),
            _make_result(
                "$pageview", "$pageview", "dormant", [-20, -15, -10], ["2025-01-01", "2025-01-02", "2025-01-03"]
            ),
        ]

        self.assertEqual(
            LifecycleResultsFormatter(
                AssistantLifecycleQuery(series=[AssistantLifecycleEventsNode(event="$pageview")]),
                results,
            ).format(),
            "Date|New|Returning|Resurrecting|Dormant\n"
            "2025-01-01|100|50|10|-20\n"
            "2025-01-02|80|40|8|-15\n"
            "2025-01-03|60|30|6|-10",
        )

    def test_format_multi_series(self):
        results = [
            _make_result("$pageview", "$pageview", "new", [100, 80], ["2025-01-01", "2025-01-02"], order=0),
            _make_result("$pageview", "$pageview", "returning", [50, 40], ["2025-01-01", "2025-01-02"], order=0),
            _make_result("$pageview", "$pageview", "resurrecting", [10, 8], ["2025-01-01", "2025-01-02"], order=0),
            _make_result("$pageview", "$pageview", "dormant", [-20, -15], ["2025-01-01", "2025-01-02"], order=0),
            _make_result("sign_up", "sign_up", "new", [30, 25], ["2025-01-01", "2025-01-02"], order=1),
            _make_result("sign_up", "sign_up", "returning", [15, 12], ["2025-01-01", "2025-01-02"], order=1),
            _make_result("sign_up", "sign_up", "resurrecting", [5, 3], ["2025-01-01", "2025-01-02"], order=1),
            _make_result("sign_up", "sign_up", "dormant", [-8, -6], ["2025-01-01", "2025-01-02"], order=1),
        ]

        self.assertEqual(
            LifecycleResultsFormatter(
                LifecycleQuery(
                    series=[
                        EventsNode(event="$pageview"),
                        EventsNode(event="sign_up"),
                    ]
                ),
                results,
            ).format(),
            "Event: $pageview\n"
            "Date|New|Returning|Resurrecting|Dormant\n"
            "2025-01-01|100|50|10|-20\n"
            "2025-01-02|80|40|8|-15\n"
            "\n"
            "Event: sign_up\n"
            "Date|New|Returning|Resurrecting|Dormant\n"
            "2025-01-01|30|15|5|-8\n"
            "2025-01-02|25|12|3|-6",
        )

    def test_format_empty_results(self):
        self.assertEqual(
            LifecycleResultsFormatter(
                AssistantLifecycleQuery(series=[AssistantLifecycleEventsNode(event="$pageview")]),
                [],
            ).format(),
            "No data recorded for this time period.",
        )

    def test_format_custom_name(self):
        results = [
            _make_result(
                "255320",
                "[growth] Soft Activation",
                "new",
                [6936],
                ["2025-10-01"],
                custom_name="Yes",
            ),
            _make_result(
                "255320",
                "[growth] Soft Activation",
                "returning",
                [29541],
                ["2025-10-01"],
                custom_name="Yes",
            ),
            _make_result(
                "255320",
                "[growth] Soft Activation",
                "resurrecting",
                [13263],
                ["2025-10-01"],
                custom_name="Yes",
            ),
            _make_result(
                "255320",
                "[growth] Soft Activation",
                "dormant",
                [-16735],
                ["2025-10-01"],
                custom_name="Yes",
            ),
        ]

        # Single series should not include the Event: header
        formatted = LifecycleResultsFormatter(
            AssistantLifecycleQuery(series=[AssistantLifecycleEventsNode(event="$pageview")]),
            results,
        ).format()

        self.assertEqual(
            formatted,
            "Date|New|Returning|Resurrecting|Dormant\n2025-10-01|6936|29541|13263|-16735",
        )

    def test_format_missing_status(self):
        # Only new and dormant statuses present
        results = [
            _make_result("$pageview", "$pageview", "new", [100, 80], ["2025-01-01", "2025-01-02"]),
            _make_result("$pageview", "$pageview", "dormant", [-20, -15], ["2025-01-01", "2025-01-02"]),
        ]

        self.assertEqual(
            LifecycleResultsFormatter(
                AssistantLifecycleQuery(series=[AssistantLifecycleEventsNode(event="$pageview")]),
                results,
            ).format(),
            "Date|New|Returning|Resurrecting|Dormant\n2025-01-01|100|0|0|-20\n2025-01-02|80|0|0|-15",
        )

    def test_format_with_datetime_seconds(self):
        results = [
            _make_result(
                "$pageview",
                "$pageview",
                "new",
                [100],
                ["2025-01-01T00:00:00-08:00"],
            ),
            _make_result(
                "$pageview",
                "$pageview",
                "returning",
                [50],
                ["2025-01-01T00:00:00-08:00"],
            ),
            _make_result(
                "$pageview",
                "$pageview",
                "resurrecting",
                [10],
                ["2025-01-01T00:00:00-08:00"],
            ),
            _make_result(
                "$pageview",
                "$pageview",
                "dormant",
                [-20],
                ["2025-01-01T00:00:00-08:00"],
            ),
        ]

        self.assertEqual(
            LifecycleResultsFormatter(
                AssistantLifecycleQuery(series=[AssistantLifecycleEventsNode(event="$pageview")]),
                results,
            ).format(),
            "Date|New|Returning|Resurrecting|Dormant\n2025-01-01 00:00|100|50|10|-20",
        )
