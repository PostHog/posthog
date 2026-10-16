import json

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import JsonValue
from rest_framework.exceptions import PermissionDenied

from posthog.hogql.parser import parse_expr
from posthog.hogql.property_access_types import RestrictedProperty

from posthog.models import PropertyDefinition, Team, User

from products.cdp.backend.filters import FilterPropertyReferences
from products.cdp.backend.mcp_event_filters import MCPEventFilterAccessValidator
from products.cdp.backend.mcp_event_properties import MCPEventPropertyAccess


class TestMCPEventPropertyMasking(SimpleTestCase):
    @parameterized.expand(
        [
            (
                {"$groups": {"org%2Ename": "hidden"}, "$group_0": "hidden", "plan": "visible"},
                {"$groups.org%2Ename"},
                {"$groups": {}, "plan": "visible"},
                "org%2Ename",
            ),
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
                    "plan": "visible",
                },
                {"$feature_flags"},
                {"plan": "visible"},
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
        self,
        properties: dict[str, JsonValue],
        restrictions: set[str],
        expected: dict[str, JsonValue],
        group_type: str = "organization",
    ) -> None:
        original = json.loads(json.dumps(properties))
        with patch(
            "products.cdp.backend.mcp_event_properties.get_group_types_for_project",
            return_value=[
                {"group_type_index": 0, "group_type": group_type},
                {"group_type_index": 1, "group_type": "project"},
            ],
        ):
            restrictions = MCPEventPropertyAccess.with_group_aliases(restrictions, team=Team(project_id=1))
        self.assertEqual(MCPEventPropertyAccess.redact(properties, restrictions), expected)
        self.assertEqual(properties, original)


class TestMCPEventFilterReferences(SimpleTestCase):
    @parameterized.expand(
        [
            ("properties.plan = 'example'", {"event": ["plan"]}),
            ("events.properties.customer.region = 'example'", {"event": ["customer.region"]}),
            ("properties IS NOT NULL", {"event": [None]}),
            ("person.properties.plan = 'example'", {"person": ["plan"]}),
            ("person IS NOT NULL", {"person": [None]}),
            ("pdi.person.properties.plan = 'example'", {"person": ["plan"]}),
            ("pdi.person.properties IS NOT NULL", {"person": [None]}),
            ("pdi IS NOT NULL", {"person": [None]}),
            ("group_0.properties.plan = 'example'", {"group:0": ["plan"]}),
            ("group_0 IS NOT NULL", {"group:0": [None]}),
            ("`$group_0` = 'example'", {"event": ["$group_0"]}),
            ("elements_chain_texts IS NOT NULL", {"event": ["$elements_chain"]}),
            ("arrayExists(properties -> properties = 'x', ['x'])", {}),
            ("arrayExists(events -> events.properties = 'x', ['x'])", {}),
            ("arrayExists(person -> person.properties = 'x', ['x'])", {}),
            ("arrayExists(properties -> properties = 'x', ['x']) AND properties.plan = 'example'", {"event": ["plan"]}),
            ("arrayExists(properties -> arrayExists(person -> properties = person, ['x']), ['x'])", {}),
            (
                "arrayExists(properties -> arrayExists(person -> properties = person, ['x']) AND person.properties.plan = 'example', ['x'])",
                {"person": ["plan"]},
            ),
            ("arrayExists(properties -> properties = 'x', events.properties.items)", {"event": ["items"]}),
            ("arrayExists(x -> x = properties.plan, ['x'])", {"event": ["plan"]}),
        ]
    )
    def test_dependencies_include_free_property_reads_only(
        self, expression: str, expected: dict[str, list[str | None]]
    ) -> None:
        visitor = FilterPropertyReferences()
        visitor.visit(parse_expr(expression))
        self.assertEqual(visitor.references, expected)


class TestMCPEventFilterAccess(SimpleTestCase):
    @parameterized.expand(["$feature/secret", "$feature_flags", "$feature_flags.secret", "$active_feature_flags"])
    def test_restricted_flag_map_denies_all_aliases(self, alias: str) -> None:
        with self.assertRaises(PermissionDenied):
            MCPEventPropertyAccess.validate(alias, {"$feature_flags"})
        MCPEventPropertyAccess.validate("plan", {"$feature_flags"})

    @parameterized.expand(
        [
            ("event", PropertyDefinition.Type.EVENT, None),
            ("person", PropertyDefinition.Type.PERSON, None),
            ("group:0", PropertyDefinition.Type.GROUP, 0),
        ]
    )
    def test_snapshot_accepts_unrelated_properties_and_rejects_restricted_reads(
        self,
        scope: str,
        property_type: int,
        group_type_index: int | None,
    ) -> None:
        team = Team(pk=1, project_id=1)
        user = User(pk=1)
        with (
            patch(
                "products.cdp.backend.mcp_event_filters.get_restricted_properties_with_group_type_index_for_team",
                return_value={
                    RestrictedProperty(name="secret", property_type=property_type, group_type_index=group_type_index)
                },
            ),
            patch("posthog.models.event.new_events_schema.use_new_events_schema", return_value=False),
        ):
            MCPEventFilterAccessValidator.validate_snapshot({scope: ["public"]}, team=team, user=user)
            for name in ("secret", None):
                with self.assertRaises(PermissionDenied):
                    MCPEventFilterAccessValidator.validate_snapshot({scope: [name]}, team=team, user=user)
