from django.test import SimpleTestCase

from parameterized import parameterized

from products.cohorts.backend.models.leaf_shape import extract_leaf_shape_hash, walk_filter_leaves


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
        self.assertNotEqual(
            extract_leaf_shape_hash(self._filters(self._behavioral())),
            extract_leaf_shape_hash(self._filters(self._behavioral(**{field: changed_value}))),
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

    def test_empty_or_null_group_values_are_safe(self) -> None:
        self.assertEqual(extract_leaf_shape_hash(None), "")
        self.assertEqual(extract_leaf_shape_hash(self._filters()), "")
        self.assertEqual(list(walk_filter_leaves({"type": "AND", "values": None})), [])
