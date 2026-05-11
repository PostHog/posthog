from posthog.test.base import BaseTest

from posthog.models import PropertyDefinition

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import (
    PropertyAccessLevel,
    get_default_access_level,
    get_property_access_level,
    get_restricted_properties_for_team,
)


class TestGetDefaultAccessLevel(BaseTest):
    def test_default_is_read_write(self):
        assert get_default_access_level() == PropertyAccessLevel.READ_WRITE


class TestGetPropertyAccessLevel(BaseTest):
    def setUp(self):
        super().setUp()
        self.prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="secret_field",
            property_type="String",
            type=PropertyDefinition.Type.EVENT,
        )

    def test_no_rules_returns_default(self):
        level = get_property_access_level(property=self.prop_def, user=self.user)
        assert level == PropertyAccessLevel.READ_WRITE

    def test_default_rule_denies_access(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.NONE.value,
        )
        level = get_property_access_level(property=self.prop_def, user=self.user)
        assert level == PropertyAccessLevel.NONE

    def test_default_rule_read_write(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.READ_WRITE.value,
        )
        level = get_property_access_level(property=self.prop_def, user=self.user)
        assert level == PropertyAccessLevel.READ_WRITE

    def test_default_rule_read(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.READ.value,
        )
        level = get_property_access_level(property=self.prop_def, user=self.user)
        assert level == PropertyAccessLevel.READ
        assert level.grants_access()

    def test_read_level_grants_access_like_read_write(self):
        # default: none
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.NONE.value,
        )
        # user-specific: read (should grant access just like read_write)
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.READ.value,
            organization_member=self.organization_membership,
        )
        level = get_property_access_level(property=self.prop_def, user=self.user)
        assert level == PropertyAccessLevel.READ
        assert level.grants_access()

    def test_read_role_rule_grants_access(self):
        from ee.models.rbac.role import Role, RoleMembership

        role = Role.objects.create(name="Reader", organization=self.organization)
        RoleMembership.objects.create(role=role, user=self.user, organization_member=self.organization_membership)

        # default: none
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.NONE.value,
        )
        # role: read
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.READ.value,
            role=role,
        )
        level = get_property_access_level(property=self.prop_def, user=self.user)
        assert level == PropertyAccessLevel.READ
        assert level.grants_access()

    def test_grants_access_helper(self):
        assert PropertyAccessLevel.READ_WRITE.grants_access() is True
        assert PropertyAccessLevel.READ.grants_access() is True
        assert PropertyAccessLevel.NONE.grants_access() is False

    def test_user_specific_rule_overrides_default(self):
        # default rule: none
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.NONE.value,
        )
        # user-specific rule: read_write
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.READ_WRITE.value,
            organization_member=self.organization_membership,
        )
        level = get_property_access_level(property=self.prop_def, user=self.user)
        assert level == PropertyAccessLevel.READ_WRITE

    def test_user_specific_none_overrides_read_write_default(self):
        # default rule: read_write
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.READ_WRITE.value,
        )
        # user-specific rule: none
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.NONE.value,
            organization_member=self.organization_membership,
        )
        level = get_property_access_level(property=self.prop_def, user=self.user)
        assert level == PropertyAccessLevel.NONE

    def test_role_rule_overrides_default(self):
        from ee.models.rbac.role import Role, RoleMembership

        role = Role.objects.create(name="Analyst", organization=self.organization)
        RoleMembership.objects.create(role=role, user=self.user, organization_member=self.organization_membership)

        # default rule: none
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.NONE.value,
        )
        # role rule: read_write
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.READ_WRITE.value,
            role=role,
        )
        level = get_property_access_level(property=self.prop_def, user=self.user)
        assert level == PropertyAccessLevel.READ_WRITE

    def test_user_rule_takes_priority_over_role_rule(self):
        from ee.models.rbac.role import Role, RoleMembership

        role = Role.objects.create(name="Viewer", organization=self.organization)
        RoleMembership.objects.create(role=role, user=self.user, organization_member=self.organization_membership)

        # role rule: read_write
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.READ_WRITE.value,
            role=role,
        )
        # user-specific rule: none
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.NONE.value,
            organization_member=self.organization_membership,
        )
        level = get_property_access_level(property=self.prop_def, user=self.user)
        assert level == PropertyAccessLevel.NONE

    def test_multiple_roles_most_permissive_wins(self):
        from ee.models.rbac.role import Role, RoleMembership

        role_viewer = Role.objects.create(name="Viewer", organization=self.organization)
        role_analyst = Role.objects.create(name="Analyst", organization=self.organization)
        RoleMembership.objects.create(
            role=role_viewer, user=self.user, organization_member=self.organization_membership
        )
        RoleMembership.objects.create(
            role=role_analyst, user=self.user, organization_member=self.organization_membership
        )

        # viewer role: none
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.NONE.value,
            role=role_viewer,
        )
        # analyst role: read_write
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.READ_WRITE.value,
            role=role_analyst,
        )
        level = get_property_access_level(property=self.prop_def, user=self.user)
        assert level == PropertyAccessLevel.READ_WRITE

    def test_no_user_returns_default_rule(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.NONE.value,
        )
        level = get_property_access_level(property=self.prop_def, user=None)
        assert level == PropertyAccessLevel.NONE

    def test_no_user_no_rules_returns_default_level(self):
        level = get_property_access_level(property=self.prop_def, user=None)
        assert level == PropertyAccessLevel.READ_WRITE

    def test_different_user_not_affected_by_other_user_rule(self):
        other_user = self._create_user("other@posthog.com")

        # user-specific rule for self.user: none
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.NONE.value,
            organization_member=self.organization_membership,
        )
        # other_user should not be affected
        level = get_property_access_level(property=self.prop_def, user=other_user)
        assert level == PropertyAccessLevel.READ_WRITE


class TestGetRestrictedPropertiesForTeam(BaseTest):
    def setUp(self):
        super().setUp()
        self.event_prop = PropertyDefinition.objects.create(
            team=self.team,
            name="secret_event_prop",
            property_type="String",
            type=PropertyDefinition.Type.EVENT,
        )
        self.person_prop = PropertyDefinition.objects.create(
            team=self.team,
            name="secret_person_prop",
            property_type="String",
            type=PropertyDefinition.Type.PERSON,
        )

    def test_no_rules_returns_empty(self):
        restricted = get_restricted_properties_for_team(team_id=self.team.pk, user=self.user)
        assert restricted == set()

    def test_denied_event_property(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        restricted = get_restricted_properties_for_team(team_id=self.team.pk, user=self.user)
        assert restricted == {("secret_event_prop", PropertyDefinition.Type.EVENT)}

    def test_denied_person_property(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.person_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        restricted = get_restricted_properties_for_team(team_id=self.team.pk, user=self.user)
        assert restricted == {("secret_person_prop", PropertyDefinition.Type.PERSON)}

    def test_multiple_denied_properties(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.person_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        restricted = get_restricted_properties_for_team(team_id=self.team.pk, user=self.user)
        assert restricted == {
            ("secret_event_prop", PropertyDefinition.Type.EVENT),
            ("secret_person_prop", PropertyDefinition.Type.PERSON),
        }

    def test_read_write_properties_not_included(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.READ_WRITE.value,
        )
        restricted = get_restricted_properties_for_team(team_id=self.team.pk, user=self.user)
        assert restricted == set()

    def test_read_properties_not_included(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.READ.value,
        )
        restricted = get_restricted_properties_for_team(team_id=self.team.pk, user=self.user)
        assert restricted == set()

    def test_user_specific_override_removes_from_restricted(self):
        # default: none
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        # user-specific: read_write
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.READ_WRITE.value,
            organization_member=self.organization_membership,
        )
        restricted = get_restricted_properties_for_team(team_id=self.team.pk, user=self.user)
        assert restricted == set()

    def test_role_override_removes_from_restricted(self):
        from ee.models.rbac.role import Role, RoleMembership

        role = Role.objects.create(name="Analyst", organization=self.organization)
        RoleMembership.objects.create(role=role, user=self.user, organization_member=self.organization_membership)

        # default: none
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )
        # role: read_write
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.READ_WRITE.value,
            role=role,
        )
        restricted = get_restricted_properties_for_team(team_id=self.team.pk, user=self.user)
        assert restricted == set()
