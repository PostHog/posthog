import json
from typing import TYPE_CHECKING

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import JsonValue

if TYPE_CHECKING:
    pass

from posthog.models import Team

from products.cdp.backend.mcp_event_properties import MCPEventPropertyAccess


class TestMCPEventPropertyMasking(SimpleTestCase):
    @parameterized.expand(
        [
            (
                {
                    "$groups": {"organization": "hidden", "project": "visible"},
                    "$group_0": "hidden",
                    "$group_1": "visible",
                },
                {"$groups.organization"},
                {"$groups": {"project": "visible"}, "$group_1": "visible"},
            ),
            (
                {"$groups.organization": "hidden", "$groups%2Eorganization": "hidden", "plan": "visible"},
                {"$groups.organization"},
                {"plan": "visible"},
            ),
            (
                {
                    "customer": {"ssn": "hidden"},
                    "customer.ssn": "hidden",
                    "customer%2Essn": "hidden",
                    "customer_name": "visible",
                },
                {"customer"},
                {"customer_name": "visible"},
            ),
            (
                {
                    "$groups": {"organization": "hidden", "project": "visible"},
                    "$group_0": "hidden",
                    "$group_1": "visible",
                },
                {"$group_0"},
                {"$groups": {"project": "visible"}, "$group_1": "visible"},
            ),
            (
                {"$groups": {"organization": "hidden"}, "$group_0": "hidden", "$group_4": "hidden", "plan": "visible"},
                {"$groups"},
                {"plan": "visible"},
            ),
            (
                {"$groups": {"organization": "hidden"}, "$group_4": "hidden", "plan": "visible"},
                {"$group_4"},
                {"plan": "visible"},
            ),
            (
                {"$groups%2Eorganization": "hidden", "$group_0": "hidden", "$group_4": "hidden", "$group_1": "visible"},
                {"$groups%2Eorganization"},
                {"$group_1": "visible"},
            ),
            (
                {"customer%2Eprofile": {"ssn": "hidden", "public": "visible"}, "customer.profile.ssn.child": "hidden"},
                {"customer.profile.ssn"},
                {"customer%2Eprofile": {"public": "visible"}},
            ),
            (
                {"items": [{"secret": "hidden", "public": "visible"}]},
                {"items.secret"},
                {"items": [{"public": "visible"}]},
            ),
            (
                {
                    "$feature/secret": True,
                    "$active_feature_flags": ["secret", "public"],
                    "$feature_flags": {"secret": True, "public": False},
                },
                {"$feature/secret"},
                {"$active_feature_flags": ["public"], "$feature_flags": {"public": False}},
            ),
        ]
    )
    def test_redacts_restricted_paths_and_feature_flag_aliases(
        self, properties: dict[str, JsonValue], restrictions: set[str], expected: dict[str, JsonValue]
    ) -> None:
        original = json.loads(json.dumps(properties))
        with patch(
            "products.cdp.backend.mcp_event_properties.get_group_types_for_project",
            return_value=[
                {"group_type_index": 0, "group_type": "organization"},
                {"group_type_index": 1, "group_type": "project"},
            ],
        ):
            restrictions = MCPEventPropertyAccess.with_group_aliases(restrictions, team=Team(project_id=1))
        self.assertEqual(MCPEventPropertyAccess.redact(properties, restrictions), expected)
        self.assertEqual(properties, original)
