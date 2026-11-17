from typing import Any, Optional

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.activity_logging.property_value_visibility import (
    PropertyValueVisibility,
    group_property_names_for_type,
    group_type_index_of,
)

TEAM_ID = 1
NAMES_BY_TYPE: dict[Optional[int], frozenset[str]] = {
    0: frozenset({"plan"}),
    1: frozenset({"customer.ssn"}),
    None: frozenset({"region"}),
}


def _detail(name: str, group_type_index: Optional[int]) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "name": name,
        "changes": [{"type": "Group", "action": "changed", "before": "before-value", "after": "after-value"}],
    }
    if group_type_index is not None:
        detail["context"] = {"group_type_index": group_type_index}
    return detail


class TestPropertyValueVisibility(SimpleTestCase):
    def _visibility(self) -> PropertyValueVisibility:
        visibility = PropertyValueVisibility(None)
        visibility._restricted_group_properties[TEAM_ID] = NAMES_BY_TYPE
        return visibility

    @parameterized.expand(
        [
            ("rule_on_same_type", "plan", 0, True),
            ("rule_on_other_type", "plan", 1, False),
            ("without_type_matches_any_type", "plan", None, True),
            ("rule_on_every_type", "region", 3, True),
            ("parent_of_nested_rule", "customer", 1, True),
            ("parent_of_nested_rule_on_other_type", "customer", 0, False),
            ("flat_key_of_nested_rule", "customer.ssn", 1, True),
            ("child_of_rule", "plan.tier", 0, True),
            ("sibling_of_nested_rule", "customer.tier", 1, False),
            ("parent_without_type", "customer", None, True),
            ("unrestricted", "industry", 0, False),
        ]
    )
    def test_apply_matches_rules_by_group_type_and_path(
        self, _name: str, property_name: str, group_type_index: Optional[int], hidden: bool
    ) -> None:
        entry = ActivityLog(scope="Group", team_id=TEAM_ID)
        detail = _detail(property_name, group_type_index)

        result = self._visibility().apply(entry, detail)

        change = result["changes"][0]
        assert (change["before"] is None and change["after"] is None) is hidden
        assert result["name"] == property_name
        assert result.get("context") == detail.get("context")

    @parameterized.expand([("rule_on_other_type", "plan", 1, False), ("rule_on_same_type", "plan", 0, True)])
    def test_apply_reads_group_type_from_stored_entry(
        self, _name: str, property_name: str, group_type_index: int, hidden: bool
    ) -> None:
        entry = ActivityLog(scope="Group", team_id=TEAM_ID, detail=_detail(property_name, group_type_index))
        serialized = _detail(property_name, None)

        change = self._visibility().apply(entry, serialized)["changes"][0]

        assert (change["before"] is None and change["after"] is None) is hidden

    def test_apply_leaves_other_scopes(self) -> None:
        detail = _detail("plan", 0)

        assert self._visibility().apply(ActivityLog(scope="FeatureFlag", team_id=TEAM_ID), detail) is detail

    @parameterized.expand(
        [
            ("missing", {}, None),
            ("null_context", {"context": None}, None),
            ("int", {"context": {"group_type_index": 2}}, 2),
            ("string", {"context": {"group_type_index": "2"}}, None),
            ("bool", {"context": {"group_type_index": True}}, None),
        ]
    )
    def test_group_type_index_of(self, _name: str, detail: dict[str, Any], expected: Optional[int]) -> None:
        assert group_type_index_of(detail) == expected

    @parameterized.expand(
        [
            ("known_type", 0, {"plan", "region"}),
            ("type_without_rules", 4, {"region"}),
            ("without_type", None, {"plan", "customer.ssn", "region"}),
        ]
    )
    def test_group_property_names_for_type(
        self, _name: str, group_type_index: Optional[int], expected: set[str]
    ) -> None:
        assert group_property_names_for_type(NAMES_BY_TYPE, group_type_index) == expected
