from django.test import SimpleTestCase

from parameterized import parameterized

from products.cohorts.backend.models.leaf_shape import (
    extract_behavioral_leaf_shape_hash,
    extract_leaf_shape_hash,
    walk_filter_leaves,
)


class TestLeafShape(SimpleTestCase):
    def _filters(self, *leaves: dict) -> dict:
        return {"properties": {"type": "AND", "values": list(leaves)}}

    def _behavioral(self, **overrides: object) -> dict:
        leaf = {
            "type": "behavioral",
            "key": "$pageview",
            "value": "performed_event_multiple",
            "time_value": 7,
            "time_interval": "day",
            "conditionHash": "cd0863735b457170",
            "operator": "gte",
            "operator_value": 3,
        }
        leaf.update(overrides)
        return leaf

    @parameterized.expand(
        [
            ("condition_hash", "conditionHash", "ffffffffffffffff"),
            ("value", "value", "performed_event"),
            ("time_value", "time_value", 30),
            ("time_interval", "time_interval", "week"),
            ("explicit_datetime", "explicit_datetime", "2026-01-01T00:00:00Z"),
            ("explicit_datetime_to", "explicit_datetime_to", "2026-02-01T00:00:00Z"),
            ("operator", "operator", "lte"),
            ("operator_value", "operator_value", 5),
        ]
    )
    def test_each_behavioral_state_field_changes_the_hash(self, _name: str, field: str, changed_value: object) -> None:
        baseline = self._filters(self._behavioral())
        changed = self._filters(self._behavioral(**{field: changed_value}))
        self.assertNotEqual(
            extract_leaf_shape_hash(baseline),
            extract_leaf_shape_hash(changed),
        )
        self.assertNotEqual(
            extract_behavioral_leaf_shape_hash(baseline),
            extract_behavioral_leaf_shape_hash(changed),
        )

    def test_behavioral_negation_and_leaf_order_do_not_change_the_hash(self) -> None:
        person = {"type": "person", "conditionHash": "aaaaaaaaaaaaaaaa"}
        self.assertEqual(
            extract_leaf_shape_hash(self._filters(self._behavioral(negation=False), person)),
            extract_leaf_shape_hash(self._filters(person, self._behavioral(negation=True))),
        )

    def test_person_and_cohort_reference_fields_are_included(self) -> None:
        self.assertNotEqual(
            extract_leaf_shape_hash(self._filters({"type": "person", "conditionHash": "a"})),
            extract_leaf_shape_hash(self._filters({"type": "person", "conditionHash": "b"})),
        )
        self.assertNotEqual(
            extract_leaf_shape_hash(self._filters({"type": "cohort", "value": 42, "negation": False})),
            extract_leaf_shape_hash(self._filters({"type": "cohort", "value": 42, "negation": True})),
        )

    @parameterized.expand(
        [
            (
                "person",
                {"type": "person", "conditionHash": "a"},
                {"type": "person", "conditionHash": "b"},
            ),
            (
                "cohort",
                {"type": "cohort", "value": 42, "negation": False},
                {"type": "cohort", "value": 43, "negation": True},
            ),
        ]
    )
    def test_non_behavioral_edits_do_not_change_behavioral_hash(self, _name: str, before: dict, after: dict) -> None:
        self.assertEqual(
            extract_behavioral_leaf_shape_hash(self._filters(self._behavioral(), before)),
            extract_behavioral_leaf_shape_hash(self._filters(self._behavioral(), after)),
        )

    def test_numeric_fields_match_rust_integer_parsing(self) -> None:
        rust_defaults = self._filters(self._behavioral(time_value=None, operator_value=None))
        invalid_numbers = self._filters(self._behavioral(time_value="30", operator_value=3.0))
        integers = self._filters(self._behavioral(time_value=30, operator_value=3))

        self.assertEqual(
            extract_behavioral_leaf_shape_hash(rust_defaults),
            extract_behavioral_leaf_shape_hash(invalid_numbers),
        )
        self.assertNotEqual(
            extract_behavioral_leaf_shape_hash(rust_defaults),
            extract_behavioral_leaf_shape_hash(integers),
        )

    def test_leaves_nested_in_inner_groups_are_walked(self) -> None:
        # Real cohorts nest leaves inside inner OR/AND groups; the hash must be identical to the
        # flat form and non-empty, so a regression that stopped recursing past the top level
        # (silently dropping nested leaves to an empty hash) is caught.
        nested = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {"type": "OR", "values": [self._behavioral()]},
                        ],
                    }
                ],
            }
        }
        flat_hash = extract_behavioral_leaf_shape_hash(self._filters(self._behavioral()))
        self.assertNotEqual(flat_hash, "")
        self.assertEqual(extract_behavioral_leaf_shape_hash(nested), flat_hash)

    def test_empty_or_null_group_values_are_safe(self) -> None:
        self.assertEqual(extract_leaf_shape_hash(None), "")
        self.assertEqual(extract_leaf_shape_hash(self._filters()), "")
        self.assertEqual(list(walk_filter_leaves({"type": "AND", "values": None})), [])
