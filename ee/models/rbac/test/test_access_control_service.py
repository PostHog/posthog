from posthog.test.base import APIBaseTest

from rest_framework import exceptions

from posthog.models.organization import OrganizationMembership

from ee.models.rbac.access_control import AccessControl
from ee.models.rbac.access_control_service import (
    get_resource_name,
    grant_access,
    list_grants,
    resolve_member_by_email,
    resolve_resource_by_name,
    resolve_role_by_name,
    revoke_access,
    validate_access_level,
    validate_resource,
)
from ee.models.rbac.role import Role


class TestAccessControlService(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Make user an org admin so they can grant access
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        self.role = Role.objects.create(
            name="Test Role",
            organization=self.organization,
            created_by=self.user,
        )

    def test_validate_resource_valid(self):
        validate_resource("insight")

    def test_validate_resource_invalid(self):
        with self.assertRaises(ValueError):
            validate_resource("nonexistent")

    def test_validate_access_level_valid(self):
        validate_access_level("insight", "editor")

    def test_validate_access_level_invalid(self):
        with self.assertRaises(ValueError):
            validate_access_level("insight", "admin")

    def test_validate_access_level_below_minimum(self):
        # action has minimum "viewer"
        with self.assertRaises(ValueError):
            validate_access_level("action", "none")

    def test_resolve_role_by_name(self):
        resolved = resolve_role_by_name(self.organization, "Test Role")
        assert resolved.id == self.role.id

    def test_resolve_role_by_name_not_found(self):
        with self.assertRaises(ValueError):
            resolve_role_by_name(self.organization, "Nonexistent")

    def test_resolve_member_by_email(self):
        resolved = resolve_member_by_email(self.organization, self.user.email)
        assert resolved.user_id == self.user.id

    def test_resolve_member_by_email_not_found(self):
        with self.assertRaises(ValueError):
            resolve_member_by_email(self.organization, "nobody@example.com")

    def test_grant_access_to_role(self):
        ac = grant_access(
            team=self.team,
            user=self.user,
            resource="insight",
            access_level="editor",
            role=self.role,
        )
        assert ac.resource == "insight"
        assert ac.access_level == "editor"
        assert ac.role_id == self.role.id
        assert ac.organization_member_id is None

    def test_grant_access_to_member(self):
        ac = grant_access(
            team=self.team,
            user=self.user,
            resource="dashboard",
            access_level="viewer",
            organization_member=self.organization_membership,
        )
        assert ac.resource == "dashboard"
        assert ac.access_level == "viewer"
        assert ac.organization_member_id == self.organization_membership.id

    def test_grant_access_default(self):
        ac = grant_access(
            team=self.team,
            user=self.user,
            resource="insight",
            access_level="viewer",
        )
        assert ac.role_id is None
        assert ac.organization_member_id is None

    def test_grant_access_upsert(self):
        grant_access(team=self.team, user=self.user, resource="insight", access_level="viewer", role=self.role)
        ac = grant_access(team=self.team, user=self.user, resource="insight", access_level="editor", role=self.role)
        assert ac.access_level == "editor"
        assert AccessControl.objects.filter(team=self.team, resource="insight", role=self.role).count() == 1

    def test_grant_access_both_role_and_member_raises(self):
        with self.assertRaises(ValueError):
            grant_access(
                team=self.team,
                user=self.user,
                resource="insight",
                access_level="editor",
                role=self.role,
                organization_member=self.organization_membership,
            )

    def test_grant_access_invalid_resource(self):
        with self.assertRaises(ValueError):
            grant_access(team=self.team, user=self.user, resource="bogus", access_level="editor")

    def test_grant_access_permission_denied_for_non_admin(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        with self.assertRaises(exceptions.PermissionDenied):
            grant_access(team=self.team, user=self.user, resource="insight", access_level="editor")

    def test_revoke_access(self):
        grant_access(team=self.team, user=self.user, resource="insight", access_level="editor", role=self.role)
        deleted = revoke_access(team=self.team, user=self.user, resource="insight", role=self.role)
        assert deleted is True
        assert not AccessControl.objects.filter(team=self.team, resource="insight", role=self.role).exists()

    def test_revoke_access_not_found(self):
        deleted = revoke_access(team=self.team, user=self.user, resource="insight", role=self.role)
        assert deleted is False

    def test_list_grants(self):
        grant_access(team=self.team, user=self.user, resource="insight", access_level="editor", role=self.role)
        grant_access(team=self.team, user=self.user, resource="dashboard", access_level="viewer")

        grants = list(list_grants(team=self.team))
        assert len(grants) == 2

    def test_list_grants_filtered_by_resource(self):
        grant_access(team=self.team, user=self.user, resource="insight", access_level="editor")
        grant_access(team=self.team, user=self.user, resource="dashboard", access_level="viewer")

        grants = list(list_grants(team=self.team, resource="insight"))
        assert len(grants) == 1
        assert grants[0].resource == "insight"

    def test_list_grants_filtered_by_role(self):
        grant_access(team=self.team, user=self.user, resource="insight", access_level="editor", role=self.role)
        grant_access(team=self.team, user=self.user, resource="insight", access_level="viewer")

        grants = list(list_grants(team=self.team, role=self.role))
        assert len(grants) == 1
        assert grants[0].role_id == self.role.id

    def test_resolve_resource_by_name_insight(self):
        from posthog.models import Insight

        insight = Insight.objects.create(team=self.team, name="My Funnel")
        result = resolve_resource_by_name(self.team, "insight", "My Funnel")
        assert result == str(insight.id)

    def test_resolve_resource_by_name_dashboard(self):
        from posthog.models import Dashboard

        dashboard = Dashboard.objects.create(team=self.team, name="Marketing")
        result = resolve_resource_by_name(self.team, "dashboard", "Marketing")
        assert result == str(dashboard.id)

    def test_resolve_resource_by_name_feature_flag(self):
        from posthog.models.feature_flag import FeatureFlag

        flag = FeatureFlag.objects.create(team=self.team, key="my-flag", created_by=self.user)
        result = resolve_resource_by_name(self.team, "feature_flag", "my-flag")
        assert result == str(flag.id)

    def test_resolve_resource_by_name_not_found(self):
        with self.assertRaises(ValueError, msg="not found"):
            resolve_resource_by_name(self.team, "insight", "Nonexistent")

    def test_resolve_resource_by_name_ambiguous(self):
        from posthog.models import Insight

        Insight.objects.create(team=self.team, name="Duplicate")
        Insight.objects.create(team=self.team, name="Duplicate")

        with self.assertRaises(ValueError, msg="Ambiguous"):
            resolve_resource_by_name(self.team, "insight", "Duplicate")

    def test_resolve_resource_by_name_unsupported_resource(self):
        with self.assertRaises(ValueError, msg="does not support"):
            resolve_resource_by_name(self.team, "query", "something")

    def test_get_resource_name_returns_name(self):
        from posthog.models import Insight

        insight = Insight.objects.create(team=self.team, name="Revenue Report")
        result = get_resource_name(self.team, "insight", str(insight.id))
        assert result == "Revenue Report"

    def test_get_resource_name_not_found(self):
        result = get_resource_name(self.team, "insight", "nonexistent-id")
        assert result is None

    def test_get_resource_name_unsupported_resource(self):
        result = get_resource_name(self.team, "query", "some-id")
        assert result is None
