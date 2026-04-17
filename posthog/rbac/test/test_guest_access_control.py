from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework import exceptions

from posthog.constants import AvailableFeature
from posthog.models import GuestResourceGrant, OrganizationInvite, OrganizationMembership, User
from posthog.models.insight import Insight
from posthog.models.organization import Organization
from posthog.rbac.guest_access_control import (
    accept_guest_invite,
    add_grant,
    create_pending_grants,
    guest_access_level_for_object,
    is_guest_sso_bypass_allowed,
    list_grants,
    promote_guest_to_member,
    remove_grant,
    require_admin,
    validate_guest_invite,
)

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile


class TestRequireAdmin(BaseTest):
    def test_admin_passes(self):
        OrganizationMembership.objects.filter(user=self.user).update(level=OrganizationMembership.Level.ADMIN)
        result = require_admin(organization=self.organization, user=self.user)
        self.assertEqual(result.user, self.user)

    def test_owner_passes(self):
        OrganizationMembership.objects.filter(user=self.user).update(level=OrganizationMembership.Level.OWNER)
        result = require_admin(organization=self.organization, user=self.user)
        self.assertEqual(result.user, self.user)

    def test_member_raises(self):
        OrganizationMembership.objects.filter(user=self.user).update(level=OrganizationMembership.Level.MEMBER)
        with self.assertRaises(exceptions.PermissionDenied):
            require_admin(organization=self.organization, user=self.user)

    def test_non_member_raises(self):
        outsider = User.objects.create_user(email="out@x.com", password="x", first_name="O")
        with self.assertRaises(exceptions.PermissionDenied):
            require_admin(organization=self.organization, user=outsider)


class TestPromoteGuestToMember(BaseTest):
    def setUp(self):
        super().setUp()
        OrganizationMembership.objects.filter(user=self.user).update(level=OrganizationMembership.Level.ADMIN)
        self.guest = User.objects.create_user(email="g@x.com", password="x", first_name="G")
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest, is_guest=True, bypass_sso_enforcement=True
        )

    def test_promotes_and_deletes_grants(self):
        dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)
        GuestResourceGrant.objects.create(
            organization_membership=self.guest_membership,
            team=self.team,
            resource="dashboard",
            resource_id=dashboard.id,
            is_pending=False,
        )
        removed = promote_guest_to_member(membership=self.guest_membership, promoted_by=self.user)
        self.assertEqual(removed, 1)
        self.guest_membership.refresh_from_db()
        self.assertFalse(self.guest_membership.is_guest)
        self.assertFalse(self.guest_membership.bypass_sso_enforcement)
        self.assertFalse(GuestResourceGrant.objects.filter(organization_membership=self.guest_membership).exists())

    def test_raises_if_not_guest(self):
        self.guest_membership.is_guest = False
        self.guest_membership.save()
        with self.assertRaises(exceptions.ValidationError):
            promote_guest_to_member(membership=self.guest_membership, promoted_by=self.user)

    def test_raises_if_caller_not_admin(self):
        regular = User.objects.create_user(email="r@x.com", password="x", first_name="R")
        OrganizationMembership.objects.create(
            organization=self.organization, user=regular, level=OrganizationMembership.Level.MEMBER
        )
        with self.assertRaises(exceptions.PermissionDenied):
            promote_guest_to_member(membership=self.guest_membership, promoted_by=regular)

    def test_promote_with_zero_grants(self):
        removed = promote_guest_to_member(membership=self.guest_membership, promoted_by=self.user)
        self.assertEqual(removed, 0)
        self.guest_membership.refresh_from_db()
        self.assertFalse(self.guest_membership.is_guest)


class TestGrantCRUD(BaseTest):
    def setUp(self):
        super().setUp()
        self.guest = User.objects.create_user(email="g@x.com", password="x", first_name="G")
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest, is_guest=True
        )
        self.dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)

    @parameterized.expand(
        [
            ("dashboard",),
            ("insight",),
            ("notebook",),
        ]
    )
    def test_add_grant_valid_resource(self, resource):
        grant = add_grant(
            membership=self.guest_membership,
            team_id=self.team.id,
            resource=resource,
            resource_id=1,
            created_by=self.user,
        )
        self.assertEqual(grant.resource, resource)
        self.assertFalse(grant.is_pending)

    def test_add_grant_rejects_non_guest(self):
        regular_membership = OrganizationMembership.objects.get(user=self.user)
        with self.assertRaises(exceptions.ValidationError):
            add_grant(
                membership=regular_membership,
                team_id=self.team.id,
                resource="dashboard",
                resource_id=1,
                created_by=self.user,
            )

    def test_add_grant_rejects_invalid_resource(self):
        with self.assertRaises(exceptions.ValidationError):
            add_grant(
                membership=self.guest_membership,
                team_id=self.team.id,
                resource="feature_flag",
                resource_id=1,
                created_by=self.user,
            )

    def test_list_grants_returns_matching(self):
        GuestResourceGrant.objects.create(
            organization_membership=self.guest_membership,
            team=self.team,
            resource="dashboard",
            resource_id=self.dashboard.id,
            is_pending=False,
        )
        result = list_grants(membership=self.guest_membership)
        self.assertEqual(result.count(), 1)

    def test_list_grants_empty_for_no_grants(self):
        result = list_grants(membership=self.guest_membership)
        self.assertEqual(result.count(), 0)

    def test_remove_grant_deletes(self):
        grant = GuestResourceGrant.objects.create(
            organization_membership=self.guest_membership,
            team=self.team,
            resource="dashboard",
            resource_id=self.dashboard.id,
            is_pending=False,
        )
        remove_grant(grant=grant)
        self.assertFalse(GuestResourceGrant.objects.filter(id=grant.id).exists())


class TestValidateGuestInvite(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"},
        ]
        self.organization.save()
        self.dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)
        self.valid_grants = [{"team_id": self.team.id, "resource": "dashboard", "resource_id": self.dashboard.id}]

    def test_passes_with_valid_input(self):
        validate_guest_invite(
            organization=self.organization,
            target_email="new@x.com",
            grants=self.valid_grants,
            bypass_sso_enforcement=False,
            bypass_acknowledged=False,
        )

    def test_rejects_without_access_control_feature(self):
        self.organization.available_product_features = []
        self.organization.save()
        with self.assertRaises(exceptions.ValidationError) as ctx:
            validate_guest_invite(
                organization=self.organization,
                target_email="new@x.com",
                grants=self.valid_grants,
                bypass_sso_enforcement=False,
                bypass_acknowledged=False,
            )
        self.assertIn("Access Control", str(ctx.exception))

    def test_rejects_empty_grants(self):
        with self.assertRaises(exceptions.ValidationError) as ctx:
            validate_guest_invite(
                organization=self.organization,
                target_email="new@x.com",
                grants=[],
                bypass_sso_enforcement=False,
                bypass_acknowledged=False,
            )
        self.assertIn("at least one", str(ctx.exception))

    def test_rejects_bypass_sso_without_acknowledgement(self):
        with self.assertRaises(exceptions.ValidationError) as ctx:
            validate_guest_invite(
                organization=self.organization,
                target_email="new@x.com",
                grants=self.valid_grants,
                bypass_sso_enforcement=True,
                bypass_acknowledged=False,
            )
        self.assertIn("bypass_acknowledged", str(ctx.exception))

    def test_accepts_bypass_sso_with_acknowledgement(self):
        validate_guest_invite(
            organization=self.organization,
            target_email="new@x.com",
            grants=self.valid_grants,
            bypass_sso_enforcement=True,
            bypass_acknowledged=True,
        )

    def test_rejects_existing_regular_member(self):
        existing = User.objects.create_user(email="existing@x.com", password="x", first_name="E")
        OrganizationMembership.objects.create(organization=self.organization, user=existing, is_guest=False)
        with self.assertRaises(exceptions.ValidationError) as ctx:
            validate_guest_invite(
                organization=self.organization,
                target_email="existing@x.com",
                grants=self.valid_grants,
                bypass_sso_enforcement=False,
                bypass_acknowledged=False,
            )
        self.assertIn("regular member", str(ctx.exception))

    def test_rejects_grant_with_wrong_team(self):
        other_org = Organization.objects.create(name="Other")
        other_team = other_org.teams.create(name="other-team")
        with self.assertRaises(exceptions.ValidationError) as ctx:
            validate_guest_invite(
                organization=self.organization,
                target_email="new@x.com",
                grants=[{"team_id": other_team.id, "resource": "dashboard", "resource_id": 1}],
                bypass_sso_enforcement=False,
                bypass_acknowledged=False,
            )
        self.assertIn("does not belong", str(ctx.exception))

    @parameterized.expand(
        [
            ("feature_flag",),
            ("experiment",),
            ("cohort",),
        ]
    )
    def test_rejects_invalid_resource_type(self, resource):
        with self.assertRaises(exceptions.ValidationError) as ctx:
            validate_guest_invite(
                organization=self.organization,
                target_email="new@x.com",
                grants=[{"team_id": self.team.id, "resource": resource, "resource_id": 1}],
                bypass_sso_enforcement=False,
                bypass_acknowledged=False,
            )
        self.assertIn("Invalid resource type", str(ctx.exception))

    def test_rejects_nonexistent_resource_id(self):
        with self.assertRaises(exceptions.ValidationError) as ctx:
            validate_guest_invite(
                organization=self.organization,
                target_email="new@x.com",
                grants=[{"team_id": self.team.id, "resource": "dashboard", "resource_id": 99999}],
                bypass_sso_enforcement=False,
                bypass_acknowledged=False,
            )
        self.assertIn("does not exist", str(ctx.exception))


class TestCreatePendingGrants(BaseTest):
    def setUp(self):
        super().setUp()
        self.invite = OrganizationInvite.objects.create(
            organization=self.organization, target_email="new@x.com", is_guest=True
        )
        self.dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)

    def test_creates_pending_grants(self):
        grants = create_pending_grants(
            invite=self.invite,
            grants=[{"team_id": self.team.id, "resource": "dashboard", "resource_id": self.dashboard.id}],
            created_by=self.user,
        )
        self.assertEqual(len(grants), 1)
        self.assertTrue(grants[0].is_pending)
        self.assertEqual(grants[0].invite, self.invite)
        self.assertIsNone(grants[0].organization_membership)

    def test_creates_multiple_grants(self):
        insight = Insight.objects.create(team=self.team, name="i", created_by=self.user)
        grants = create_pending_grants(
            invite=self.invite,
            grants=[
                {"team_id": self.team.id, "resource": "dashboard", "resource_id": self.dashboard.id},
                {"team_id": self.team.id, "resource": "insight", "resource_id": insight.id},
            ],
            created_by=self.user,
        )
        self.assertEqual(len(grants), 2)
        self.assertEqual({g.resource for g in grants}, {"dashboard", "insight"})


class TestAcceptGuestInvite(BaseTest):
    def setUp(self):
        super().setUp()
        self.invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="new@x.com",
            is_guest=True,
            bypass_sso_enforcement=True,
        )
        self.dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)
        GuestResourceGrant.objects.create(
            invite=self.invite,
            team=self.team,
            resource="dashboard",
            resource_id=self.dashboard.id,
            is_pending=True,
        )

    def test_creates_guest_membership(self):
        new_user = User.objects.create_user(email="new@x.com", password="x", first_name="N")
        membership = accept_guest_invite(invite=self.invite, user=new_user)
        self.assertTrue(membership.is_guest)
        self.assertTrue(membership.bypass_sso_enforcement)
        self.assertEqual(membership.organization, self.organization)

    def test_flips_grants_to_active(self):
        new_user = User.objects.create_user(email="new@x.com", password="x", first_name="N")
        membership = accept_guest_invite(invite=self.invite, user=new_user)
        grant = GuestResourceGrant.objects.get(organization_membership=membership)
        self.assertFalse(grant.is_pending)
        self.assertIsNone(grant.invite)
        self.assertEqual(grant.resource, "dashboard")
        self.assertEqual(grant.resource_id, self.dashboard.id)

    def test_handles_multiple_grants(self):
        insight = Insight.objects.create(team=self.team, name="i", created_by=self.user)
        GuestResourceGrant.objects.create(
            invite=self.invite,
            team=self.team,
            resource="insight",
            resource_id=insight.id,
            is_pending=True,
        )
        new_user = User.objects.create_user(email="new@x.com", password="x", first_name="N")
        membership = accept_guest_invite(invite=self.invite, user=new_user)
        active_grants = GuestResourceGrant.objects.filter(organization_membership=membership, is_pending=False)
        self.assertEqual(active_grants.count(), 2)


class TestGuestAccessLevelForObject(BaseTest):
    def setUp(self):
        super().setUp()
        self.guest = User.objects.create_user(email="g@x.com", password="x", first_name="G")
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest, is_guest=True
        )
        self.dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)

    def test_returns_viewer_for_direct_grant(self):
        GuestResourceGrant.objects.create(
            organization_membership=self.guest_membership,
            team=self.team,
            resource="dashboard",
            resource_id=self.dashboard.id,
            is_pending=False,
        )
        result = guest_access_level_for_object(
            org_membership=self.guest_membership,
            team=self.team,
            resource="dashboard",
            obj_id=self.dashboard.id,
        )
        self.assertEqual(result, "viewer")

    def test_returns_none_without_grant(self):
        result = guest_access_level_for_object(
            org_membership=self.guest_membership,
            team=self.team,
            resource="dashboard",
            obj_id=self.dashboard.id,
        )
        self.assertIsNone(result)

    def test_insight_inherits_from_granted_dashboard(self):
        insight = Insight.objects.create(team=self.team, name="i", created_by=self.user)
        DashboardTile.objects.create(dashboard=self.dashboard, insight=insight)
        GuestResourceGrant.objects.create(
            organization_membership=self.guest_membership,
            team=self.team,
            resource="dashboard",
            resource_id=self.dashboard.id,
            is_pending=False,
        )
        result = guest_access_level_for_object(
            org_membership=self.guest_membership,
            team=self.team,
            resource="insight",
            obj_id=insight.id,
        )
        self.assertEqual(result, "viewer")

    def test_insight_without_dashboard_grant_returns_none(self):
        insight = Insight.objects.create(team=self.team, name="i", created_by=self.user)
        DashboardTile.objects.create(dashboard=self.dashboard, insight=insight)
        result = guest_access_level_for_object(
            org_membership=self.guest_membership,
            team=self.team,
            resource="insight",
            obj_id=insight.id,
        )
        self.assertIsNone(result)

    def test_pending_grant_not_considered(self):
        invite = OrganizationInvite.objects.create(
            organization=self.organization, target_email="x@x.com", is_guest=True
        )
        GuestResourceGrant.objects.create(
            invite=invite,
            team=self.team,
            resource="dashboard",
            resource_id=self.dashboard.id,
            is_pending=True,
        )
        result = guest_access_level_for_object(
            org_membership=self.guest_membership,
            team=self.team,
            resource="dashboard",
            obj_id=self.dashboard.id,
        )
        self.assertIsNone(result)

    @parameterized.expand(
        [
            ("dashboard",),
            ("insight",),
            ("notebook",),
        ]
    )
    def test_resource_type_direct_grant(self, resource):
        GuestResourceGrant.objects.create(
            organization_membership=self.guest_membership,
            team=self.team,
            resource=resource,
            resource_id=42,
            is_pending=False,
        )
        result = guest_access_level_for_object(
            org_membership=self.guest_membership,
            team=self.team,
            resource=resource,
            obj_id=42,
        )
        self.assertEqual(result, "viewer")


class TestIsGuestSsoBypassAllowed(BaseTest):
    def setUp(self):
        super().setUp()
        from posthog.models.organization_domain import OrganizationDomain

        self.domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="x.com",
            sso_enforcement="google-oauth2",
            verified_at="2026-01-01T00:00:00Z",
        )
        self.guest = User.objects.create_user(email="g@x.com", password="x", first_name="G")
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.guest,
            is_guest=True,
            bypass_sso_enforcement=True,
        )

    def test_returns_true_when_bypass_enabled(self):
        self.assertTrue(is_guest_sso_bypass_allowed(email="g@x.com"))

    def test_returns_false_when_bypass_disabled(self):
        self.guest_membership.bypass_sso_enforcement = False
        self.guest_membership.save()
        self.assertFalse(is_guest_sso_bypass_allowed(email="g@x.com"))

    def test_returns_false_for_non_guest(self):
        regular = User.objects.create_user(email="r@x.com", password="x", first_name="R")
        OrganizationMembership.objects.create(organization=self.organization, user=regular, is_guest=False)
        self.assertFalse(is_guest_sso_bypass_allowed(email="r@x.com"))

    def test_returns_false_for_unverified_domain(self):
        self.domain.verified_at = None
        self.domain.save()
        self.assertFalse(is_guest_sso_bypass_allowed(email="g@x.com"))

    def test_returns_false_for_no_enforcement(self):
        self.domain.sso_enforcement = ""
        self.domain.save()
        self.assertFalse(is_guest_sso_bypass_allowed(email="g@x.com"))

    def test_returns_false_for_unknown_email(self):
        self.assertFalse(is_guest_sso_bypass_allowed(email="nobody@other.com"))
