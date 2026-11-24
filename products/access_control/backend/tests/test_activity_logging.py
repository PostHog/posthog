from uuid import UUID

from django.test import SimpleTestCase

from parameterized import parameterized

from products.access_control.backend.activity_logging import AccessRuleNames, AccessRuleObject, access_rule_display_name
from products.access_control.backend.models.access_control import AccessControl

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
                "unresolved_object_and_member",
                AccessControl(
                    resource="dashboard", resource_id="42", access_level="viewer", organization_member_id=SUBJECT_ID
                ),
                {},
                f"access rule for member {SUBJECT_ID} on dashboard 42",
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
        names = AccessRuleNames(objects=objects, roles={}, members={})
        assert access_rule_display_name(rule, names) == expected
