from uuid import UUID

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.access_control.backend.activity_logging import (
    AccessRuleNames,
    AccessRuleObject,
    access_rule_display_name,
    resolve_access_rule_names,
)
from products.access_control.backend.models.access_control import AccessControl
from products.canvas.backend.models import Canvas
from products.tasks.backend.models import Channel

SUBJECT_ID = UUID("01900000-0000-0000-0000-000000000001")


class TestAccessRuleDisplayName(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "resource_wide_default",
                AccessControl(resource="action", access_level="viewer"),
                {},
                "default access rule on all actions",
            ),
            (
                "unresolved_object",
                AccessControl(
                    resource="dashboard", resource_id="42", access_level="viewer", organization_member_id=SUBJECT_ID
                ),
                {},
                "access rule for a member on dashboard 42",
            ),
            (
                "unresolved_role",
                AccessControl(resource="feature_flag", resource_id="7", access_level="editor", role_id=SUBJECT_ID),
                {AccessRuleObject(resource="feature_flag", resource_id="7"): "Beta"},
                f'access rule for role {SUBJECT_ID} on feature flag "Beta"',
            ),
        ]
    )
    def test_falls_back_to_ids(
        self, _name: str, rule: AccessControl, objects: dict[AccessRuleObject, str], expected: str
    ) -> None:
        names = AccessRuleNames(objects=objects, roles={})
        assert access_rule_display_name(rule, names) == expected


class TestResolveAccessRuleNames(BaseTest):
    def test_leaves_out_names_the_product_hides_from_some_members(self) -> None:
        with team_scope(self.team.id):
            channel = Channel.objects.create(team=self.team, name="general")
            canvas = Canvas.objects.create(team=self.team, channel=channel, name="Private plans", created_by=self.user)
        rule = AccessControl(team=self.team, resource="canvas", resource_id=str(canvas.id), access_level="viewer")

        names = resolve_access_rule_names(team=self.team, rules=[rule])

        assert access_rule_display_name(rule, names) == f"default access rule on canvas {canvas.id}"
