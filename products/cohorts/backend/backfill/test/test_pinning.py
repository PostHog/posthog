from django.test import SimpleTestCase

from parameterized import parameterized

from products.cohorts.backend.backfill.pinning import derive_window_days, pin_conditions_for_cohorts
from products.cohorts.backend.models.cohort import Cohort


class TestBackfillPinning(SimpleTestCase):
    @parameterized.expand(
        [
            ("day", 3, 3),
            ("week", 3, 21),
            ("month", 3, 90),
            ("year", 3, 1095),
            ("hour", 3, 0),
            ("minute", 3, 0),
            ("invalid", "bad", 0),
        ]
    )
    def test_derive_window_days(self, interval: str, value: object, expected: int) -> None:
        self.assertEqual(derive_window_days(value, interval), expected)

    def test_pins_leaf_state_fields_and_event_union(self) -> None:
        cohort = Cohort(
            id=7,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "event_type": "events",
                            "value": "performed_event_multiple",
                            "conditionHash": "bbbbbbbbbbbbbbbb",
                            "time_value": 7,
                            "time_interval": "day",
                            "explicit_datetime": None,
                            "explicit_datetime_to": None,
                            "operator": "gte",
                            "operator_value": 3,
                        },
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "event_type": "events",
                            "value": "performed_event",
                            "conditionHash": "aaaaaaaaaaaaaaaa",
                        },
                        {
                            "type": "behavioral",
                            "key": 42,
                            "event_type": "actions",
                            "value": "performed_event",
                            "conditionHash": "cccccccccccccccc",
                        },
                    ],
                }
            },
        )

        pinned, event_names = pin_conditions_for_cohorts([cohort])

        self.assertEqual(pinned["schema_version"], 1)
        self.assertEqual(event_names, ["$pageview"])
        self.assertEqual(
            [condition["condition_hash"] for condition in pinned["conditions"]],
            sorted(
                [
                    "aaaaaaaaaaaaaaaa",
                    "bbbbbbbbbbbbbbbb",
                    "cccccccccccccccc",
                ]
            ),
        )
        multiple = next(item for item in pinned["conditions"] if item["condition_hash"] == "bbbbbbbbbbbbbbbb")
        self.assertEqual(
            {
                field: multiple[field]
                for field in (
                    "condition_hash",
                    "value",
                    "time_value",
                    "time_interval",
                    "explicit_datetime",
                    "explicit_datetime_to",
                    "operator",
                    "operator_value",
                )
            },
            {
                "condition_hash": "bbbbbbbbbbbbbbbb",
                "value": "performed_event_multiple",
                "time_value": 7,
                "time_interval": "day",
                "explicit_datetime": None,
                "explicit_datetime_to": None,
                "operator": "gte",
                "operator_value": 3,
            },
        )
        action = next(item for item in pinned["conditions"] if item["condition_hash"] == "cccccccccccccccc")
        self.assertTrue(action["is_action"])
        self.assertIsNone(action["event_name"])
