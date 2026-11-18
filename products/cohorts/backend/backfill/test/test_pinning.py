from unittest import mock

from django.test import SimpleTestCase

from parameterized import parameterized

from products.cohorts.backend.backfill.pinning import (
    PersonPinningCapExceeded,
    derive_window_days,
    leaf_unpinnable_reason,
    pin_conditions_for_cohorts,
    pin_person_conditions_for_cohorts,
)
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

    @parameterized.expand(
        [
            ("windowed_performed_event", {}, None),
            (
                "explicit_absolute_range",
                {"time_value": None, "time_interval": None, "explicit_datetime": "2026-01-03"},
                None,
            ),
            # `classify_behavioral` reads a numeric key, never `event_type`, so the catalog keeps
            # this leaf and the gate must too.
            ("action_event_type_with_a_string_key", {"event_type": "actions"}, None),
            ("sequence_value", {"value": "performed_event_sequence"}, "unsupported_behavioral_value"),
            ("action_id_key", {"key": 42}, "behavioral_action_key"),
            ("hashless", {"conditionHash": None}, "missing_condition_hash"),
            ("short_hash", {"conditionHash": "aaaa"}, "missing_condition_hash"),
            ("bytecodeless", {"bytecode": None}, "missing_bytecode"),
            ("unloadable_bytecode", {"bytecode": [1, 2, 3]}, "malformed_bytecode"),
            ("empty_key", {"key": ""}, "malformed_leaf"),
            ("windowless", {"time_value": None, "time_interval": None}, "unsupported_state_variant"),
            (
                "sub_day_multiple",
                {"value": "performed_event_multiple", "time_interval": "hour", "operator": "gte", "operator_value": 2},
                "unsupported_state_variant",
            ),
            (
                "relative_upper_bound",
                {
                    "time_value": None,
                    "time_interval": None,
                    "explicit_datetime": "2026-01-03",
                    "explicit_datetime_to": "-1d",
                },
                "unsupported_state_variant",
            ),
        ]
    )
    def test_behavioral_leaf_screening(self, _name: str, overrides: dict, expected: str | None) -> None:
        leaf = {
            "type": "behavioral",
            "key": "$pageview",
            "event_type": "events",
            "value": "performed_event",
            "conditionHash": "aaaaaaaaaaaaaaaa",
            "time_value": 7,
            "time_interval": "day",
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
            **overrides,
        }
        self.assertEqual(leaf_unpinnable_reason(leaf), expected)

    @parameterized.expand(
        [
            ("person_metadata", {"type": "person_metadata", "key": "distinct_id"}, "unknown_leaf_type"),
            ("cohort_reference", {"type": "cohort", "value": 12}, None),
            (
                "person_leaf",
                {
                    "type": "person",
                    "key": "email",
                    "conditionHash": "bbbbbbbbbbbbbbbb",
                    "bytecode": ["_H", 1, 32, "email", 32, "properties", 32, "person", 1, 3, 11],
                },
                None,
            ),
            (
                "person_leaf_without_bytecode",
                {"type": "person", "key": "email", "conditionHash": "bbbbbbbbbbbbbbbb"},
                "missing_bytecode",
            ),
        ]
    )
    def test_non_behavioral_leaves_are_screened_too(self, _name: str, leaf: dict, expected: str | None) -> None:
        # A cohort losing any leaf is `Excluded(HasDroppedLeaf)` whole, so the gate cannot look at
        # behavioral leaves alone.
        self.assertEqual(leaf_unpinnable_reason(leaf), expected)

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

    def test_an_actions_event_type_with_a_string_key_pins_as_an_event(self) -> None:
        # The catalog keeps this leaf, so the gate admits the cohort. Pinning it as an action would
        # drop the condition in the seeder and fail the run the gate just allowed.
        cohort = Cohort(
            id=7,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "event_type": "actions",
                            "value": "performed_event",
                            "conditionHash": "aaaaaaaaaaaaaaaa",
                            "time_value": 7,
                            "time_interval": "day",
                        }
                    ],
                }
            },
        )

        pinned, event_names = pin_conditions_for_cohorts([cohort])

        self.assertEqual(event_names, ["$pageview"])
        self.assertFalse(pinned["conditions"][0]["is_action"])
        self.assertEqual(pinned["conditions"][0]["event_name"], "$pageview")

    def test_person_conditions_are_sorted_and_preserved_per_cohort(self) -> None:
        second = Cohort(
            id=2,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "person", "conditionHash": "bbbbbbbbbbbbbbbb"},
                        {"type": "person", "conditionHash": "aaaaaaaaaaaaaaaa"},
                    ],
                }
            },
        )
        first = Cohort(
            id=1,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"type": "person", "conditionHash": "aaaaaaaaaaaaaaaa"}],
                }
            },
        )

        pinned = pin_person_conditions_for_cohorts([second, first], max_conditions=3)

        self.assertEqual(
            pinned,
            {
                "schema_version": 1,
                "conditions": [
                    {"cohort_id": 1, "condition_hash": "aaaaaaaaaaaaaaaa"},
                    {"cohort_id": 2, "condition_hash": "aaaaaaaaaaaaaaaa"},
                    {"cohort_id": 2, "condition_hash": "bbbbbbbbbbbbbbbb"},
                ],
            },
        )

    def test_hashless_person_leaf_is_dropped_with_warning(self) -> None:
        cohort = Cohort(
            id=7,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "person", "conditionHash": None},
                        {"type": "person", "conditionHash": "aaaaaaaaaaaaaaaa"},
                    ],
                }
            },
        )

        with mock.patch("products.cohorts.backend.backfill.pinning.logger") as logger:
            pinned = pin_person_conditions_for_cohorts([cohort], max_conditions=1)

        self.assertEqual(
            pinned["conditions"],
            [{"cohort_id": 7, "condition_hash": "aaaaaaaaaaaaaaaa"}],
        )
        logger.warning.assert_called_once_with(
            "cohort_person_backfill_hashless_leaves_dropped",
            cohort_id=7,
            dropped=1,
        )

    def test_person_condition_cap_accepts_boundary_and_rejects_next_leaf(self) -> None:
        cohort = Cohort(
            id=7,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "person", "conditionHash": "aaaaaaaaaaaaaaaa"},
                        {"type": "person", "conditionHash": "bbbbbbbbbbbbbbbb"},
                    ],
                }
            },
        )

        self.assertEqual(
            len(pin_person_conditions_for_cohorts([cohort], max_conditions=2)["conditions"]),
            2,
        )
        with self.assertRaises(PersonPinningCapExceeded):
            pin_person_conditions_for_cohorts([cohort], max_conditions=1)
