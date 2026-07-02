from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.db import DatabaseError
from django.test import SimpleTestCase

from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import (
    PropertyAccessLevel,
    _restriction_cache_var,
    _run_with_stale_connection_retry,
    get_default_access_level,
    get_property_access_level,
    get_restricted_properties_for_team,
    restriction_cache_scope,
)


def _enable_property_access_control(organization):
    organization.available_product_features = [
        {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
    ]
    organization.save()


class TestGetDefaultAccessLevel(BaseTest):
    def test_default_is_read_write(self):
        assert get_default_access_level() == PropertyAccessLevel.READ_WRITE


class TestGetPropertyAccessLevel(BaseTest):
    def setUp(self):
        super().setUp()
        _enable_property_access_control(self.organization)
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

    def test_org_admin_bypasses_default_restriction(self):
        from posthog.models import OrganizationMembership

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.NONE.value,
        )
        level = get_property_access_level(property=self.prop_def, user=self.user)
        assert level == PropertyAccessLevel.READ_WRITE

    def test_org_admin_bypasses_user_specific_restriction(self):
        from posthog.models import OrganizationMembership

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.NONE.value,
            organization_member=self.organization_membership,
        )
        level = get_property_access_level(property=self.prop_def, user=self.user)
        assert level == PropertyAccessLevel.READ_WRITE

    def test_org_admin_bypasses_role_restriction(self):
        from posthog.models import OrganizationMembership

        from ee.models.rbac.role import Role, RoleMembership

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        role = Role.objects.create(name="Restricted", organization=self.organization)
        RoleMembership.objects.create(role=role, user=self.user, organization_member=self.organization_membership)

        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.prop_def,
            access_level=PropertyAccessLevel.NONE.value,
            role=role,
        )
        level = get_property_access_level(property=self.prop_def, user=self.user)
        assert level == PropertyAccessLevel.READ_WRITE

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
        _enable_property_access_control(self.organization)
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


class TestRestrictionCacheScope(BaseTest):
    def setUp(self):
        super().setUp()
        _enable_property_access_control(self.organization)
        self.event_prop = PropertyDefinition.objects.create(
            team=self.team,
            name="secret_event_prop",
            property_type="String",
            type=PropertyDefinition.Type.EVENT,
        )

    def test_outside_scope_does_not_cache(self):
        assert _restriction_cache_var.get() is None

        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )

        with patch(
            "products.access_control.backend.property_access_control.PropertyAccessControl.objects"
        ) as mock_manager:
            mock_manager.filter.return_value.select_related.return_value.exclude.return_value.exists.return_value = (
                False
            )
            get_restricted_properties_for_team(team_id=self.team.pk, user=self.user)
            get_restricted_properties_for_team(team_id=self.team.pk, user=self.user)
            assert mock_manager.filter.call_count == 2

    def test_inside_scope_memoizes(self):
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=self.event_prop,
            access_level=PropertyAccessLevel.NONE.value,
        )

        with restriction_cache_scope():
            first = get_restricted_properties_for_team(team_id=self.team.pk, user=self.user)
            with patch(
                "products.access_control.backend.property_access_control.PropertyAccessControl.objects"
            ) as mock_manager:
                second = get_restricted_properties_for_team(team_id=self.team.pk, user=self.user)
                assert mock_manager.filter.call_count == 0

        assert first == second == {("secret_event_prop", PropertyDefinition.Type.EVENT)}
        assert _restriction_cache_var.get() is None

    def test_model_save_inside_scope_invalidates_cache(self):
        with restriction_cache_scope():
            assert get_restricted_properties_for_team(team_id=self.team.pk, user=self.user) == set()

            PropertyAccessControl.objects.create(
                team=self.team,
                property_definition=self.event_prop,
                access_level=PropertyAccessLevel.NONE.value,
            )

            # The post_save signal should have cleared the cache so we see the new restriction
            assert get_restricted_properties_for_team(team_id=self.team.pk, user=self.user) == {
                ("secret_event_prop", PropertyDefinition.Type.EVENT)
            }


class TestQueryTimeFeatureGate(BaseTest):
    """
    Without the PROPERTY_ACCESS_CONTROL entitlement, query-time enforcement must short-circuit —
    every property resolves to the default access level and no property is restricted, even when
    rules exist in the DB. (The rules stay in the DB so behavior restores cleanly if the org
    re-subscribes.)
    """

    def setUp(self):
        super().setUp()
        # Intentionally do NOT enable PROPERTY_ACCESS_CONTROL.
        self.event_prop = PropertyDefinition.objects.create(
            team=self.team,
            name="gated_event_prop",
            property_type="String",
            type=PropertyDefinition.Type.EVENT,
        )
        self.person_prop = PropertyDefinition.objects.create(
            team=self.team,
            name="gated_person_prop",
            property_type="String",
            type=PropertyDefinition.Type.PERSON,
        )

    def _create_none_rule(self, prop_def: PropertyDefinition) -> None:
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=prop_def,
            access_level=PropertyAccessLevel.NONE.value,
        )

    def test_get_property_access_level_returns_default_without_feature(self):
        self._create_none_rule(self.event_prop)
        level = get_property_access_level(property=self.event_prop, user=self.user)
        assert level == PropertyAccessLevel.READ_WRITE

    def test_get_restricted_properties_for_team_returns_empty_without_feature(self):
        self._create_none_rule(self.event_prop)
        self._create_none_rule(self.person_prop)
        restricted = get_restricted_properties_for_team(team_id=self.team.pk, user=self.user)
        assert restricted == set()

    def test_enforcement_restored_when_feature_re_enabled(self):
        self._create_none_rule(self.event_prop)
        assert get_restricted_properties_for_team(team_id=self.team.pk, user=self.user) == set()

        _enable_property_access_control(self.organization)

        assert get_restricted_properties_for_team(team_id=self.team.pk, user=self.user) == {
            ("gated_event_prop", PropertyDefinition.Type.EVENT)
        }


class TestRunWithStaleConnectionRetry(SimpleTestCase):
    def test_evicts_dead_connection_and_retries_once(self):
        # A pooled connection recycled while idle raises a corrupted-protocol DatabaseError on reuse
        # (the production "lost synchronization with server" crash in the HogQL printer's hot path);
        # the dead connection is evicted and the read succeeds on the retry.
        dead_conn = MagicMock()
        dead_conn.is_usable.return_value = False

        results = iter(
            [
                DatabaseError('lost synchronization with server: got message type "c", length 1751475051'),
                "recovered",
            ]
        )

        def operation():
            outcome = next(results)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with patch("products.access_control.backend.property_access_control.connections") as mock_connections:
            mock_connections.all.return_value = [dead_conn]
            assert _run_with_stale_connection_retry(operation) == "recovered"

        dead_conn.close.assert_called_once()

    def test_reraises_when_connection_still_usable(self):
        # A DatabaseError on a healthy connection is a genuine query failure, not connection
        # corruption — it must propagate rather than silently retry.
        healthy_conn = MagicMock()
        healthy_conn.is_usable.return_value = True

        call_count = 0

        def operation():
            nonlocal call_count
            call_count += 1
            raise DatabaseError("integrity constraint violated")

        with patch("products.access_control.backend.property_access_control.connections") as mock_connections:
            mock_connections.all.return_value = [healthy_conn]
            with self.assertRaises(DatabaseError):
                _run_with_stale_connection_retry(operation)

        assert call_count == 1
        healthy_conn.close.assert_not_called()
