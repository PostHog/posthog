from django.test import SimpleTestCase

from parameterized import parameterized

from products.cohorts.backend.models.leaf_shape import (
    extract_behavioral_leaf_shape_hash,
    extract_leaf_shape_hash,
    extract_person_leaf_shape_hash,
    walk_filter_leaves,
)


def _behavioral_leaf(**overrides: object) -> dict:
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


def _group(group_type: str, *values: dict) -> dict:
    return {"type": group_type, "values": list(values)}


_BEHAVIORAL = _behavioral_leaf()
_OTHER_BEHAVIORAL = _behavioral_leaf(conditionHash="ffffffffffffffff")
_PERSON = {"type": "person", "conditionHash": "aaaaaaaaaaaaaaaa"}
_COHORT_REF = {"type": "cohort", "value": 42}


class TestLeafShape(SimpleTestCase):
    def _filters(self, *leaves: dict) -> dict:
        return {"properties": {"type": "AND", "values": list(leaves)}}

    def _behavioral(self, **overrides: object) -> dict:
        return _behavioral_leaf(**overrides)

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

    @parameterized.expand(
        [
            (
                "root_group_operator",
                {"properties": _group("AND", _BEHAVIORAL, _PERSON)},
                {"properties": _group("OR", _BEHAVIORAL, _PERSON)},
            ),
            (
                "inner_group_operator",
                {"properties": _group("AND", _group("AND", _BEHAVIORAL, _PERSON), _COHORT_REF)},
                {"properties": _group("AND", _group("OR", _BEHAVIORAL, _PERSON), _COHORT_REF)},
            ),
            (
                "behavioral_negation",
                {"properties": _group("AND", _BEHAVIORAL, _PERSON)},
                {"properties": _group("AND", {**_BEHAVIORAL, "negation": True}, _PERSON)},
            ),
            (
                "person_negation",
                {"properties": _group("AND", _BEHAVIORAL, _PERSON)},
                {"properties": _group("AND", _BEHAVIORAL, {**_PERSON, "negation": True})},
            ),
            (
                "cohort_reference_not_in",
                {"properties": _group("AND", _BEHAVIORAL, _COHORT_REF)},
                {"properties": _group("AND", _BEHAVIORAL, {**_COHORT_REF, "operator": "not_in"})},
            ),
            (
                "leaf_moved_between_groups",
                {"properties": _group("OR", _group("AND", _BEHAVIORAL, _PERSON), _group("AND", _OTHER_BEHAVIORAL))},
                {"properties": _group("OR", _group("AND", _BEHAVIORAL), _group("AND", _OTHER_BEHAVIORAL, _PERSON))},
            ),
        ]
    )
    def test_composition_edits_move_only_the_full_hash(self, _name: str, before: dict, after: dict) -> None:
        self.assertNotEqual(extract_leaf_shape_hash(before), extract_leaf_shape_hash(after))
        self.assertEqual(
            extract_behavioral_leaf_shape_hash(before),
            extract_behavioral_leaf_shape_hash(after),
        )
        self.assertEqual(extract_person_leaf_shape_hash(before), extract_person_leaf_shape_hash(after))

    @parameterized.expand(
        [
            (
                "leaf_order",
                {"properties": _group("AND", _BEHAVIORAL, _PERSON)},
                {"properties": _group("AND", _PERSON, _BEHAVIORAL)},
            ),
            (
                "single_child_wrapper",
                {"properties": _group("AND", _BEHAVIORAL)},
                {"properties": _group("OR", _group("AND", _group("OR", _BEHAVIORAL)))},
            ),
            (
                "duplicate_leaf",
                {"properties": _group("AND", _BEHAVIORAL, _PERSON)},
                {"properties": _group("AND", _BEHAVIORAL, _PERSON, _PERSON)},
            ),
            (
                "negation_absent_or_false",
                {"properties": _group("AND", _BEHAVIORAL, _PERSON)},
                {"properties": _group("AND", {**_BEHAVIORAL, "negation": False}, {**_PERSON, "negation": False})},
            ),
            (
                "condition_hash_absent_or_null",
                {"properties": _group("AND", _BEHAVIORAL, {"type": "person", "key": "email"})},
                {"properties": _group("AND", _BEHAVIORAL, {"type": "person", "key": "email", "conditionHash": None})},
            ),
        ]
    )
    def test_semantically_null_edits_do_not_move_the_full_hash(self, _name: str, before: dict, after: dict) -> None:
        # AND and OR are commutative and idempotent, and a group of one operand is that operand, so
        # these edits describe the same cohort. Each one would otherwise fire a history replay for
        # a definition that did not change. The last two are what the API's own re-validation does
        # to an untouched definition, so they decide whether a plain rename fires a run.
        self.assertNotEqual(extract_leaf_shape_hash(before), "")
        self.assertEqual(extract_leaf_shape_hash(before), extract_leaf_shape_hash(after))

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

    def test_person_hash_uses_only_hashed_person_leaves(self) -> None:
        person = {"type": "person", "conditionHash": "aaaaaaaaaaaaaaaa"}
        baseline = extract_person_leaf_shape_hash(self._filters(person))

        self.assertNotEqual(baseline, "")
        self.assertEqual(
            baseline,
            extract_person_leaf_shape_hash(
                self._filters(
                    self._behavioral(),
                    {"type": "cohort", "value": 42, "negation": False},
                    {"type": "person", "conditionHash": None},
                    person,
                )
            ),
        )
        self.assertNotEqual(
            baseline,
            extract_person_leaf_shape_hash(self._filters({"type": "person", "conditionHash": "bbbbbbbbbbbbbbbb"})),
        )
        self.assertEqual(extract_person_leaf_shape_hash(None), "")

    def test_behavioral_edit_does_not_change_person_hash(self) -> None:
        person = {"type": "person", "conditionHash": "aaaaaaaaaaaaaaaa"}

        self.assertEqual(
            extract_person_leaf_shape_hash(self._filters(person, self._behavioral(time_value=7))),
            extract_person_leaf_shape_hash(self._filters(person, self._behavioral(time_value=30))),
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
