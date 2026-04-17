from posthog.test.base import BaseTest

from posthog.constants import AvailableFeature
from posthog.models import GuestResourceGrant, Insight, OrganizationMembership, User
from posthog.rbac.user_access_control import UserAccessControl

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile


class TestGuestUserAccessControl(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"},
        ]
        self.organization.save()
        self.guest = User.objects.create_user(email="g@posthog.com", password="x", first_name="G")
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest, is_guest=True
        )
        self.uac = UserAccessControl(user=self.guest, team=self.team)

    def test_guest_resource_level_access_is_none(self):
        self.assertEqual(self.uac.access_level_for_resource("dashboard"), "none")
        self.assertEqual(self.uac.access_level_for_resource("insight"), "none")
        self.assertEqual(self.uac.access_level_for_resource("notebook"), "none")
        self.assertEqual(self.uac.access_level_for_resource("feature_flag"), "none")

    def test_guest_object_access_without_grant_is_none(self):
        dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)
        self.assertIsNone(self.uac.access_level_for_object(dashboard))

    def test_guest_object_access_with_grant_is_viewer(self):
        dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)
        GuestResourceGrant.objects.create(
            organization_membership=self.membership,
            team=self.team,
            resource=GuestResourceGrant.Resource.DASHBOARD,
            resource_id=dashboard.id,
            is_pending=False,
        )
        self.assertEqual(self.uac.access_level_for_object(dashboard), "viewer")

    def test_guest_creator_override_disabled(self):
        dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.guest)
        self.assertIsNone(self.uac.access_level_for_object(dashboard))

    def test_guest_admin_override_disabled(self):
        self.membership.level = OrganizationMembership.Level.ADMIN
        self.membership.save()
        dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)
        self.assertIsNone(self.uac.access_level_for_object(dashboard))

    def test_guest_insight_tile_inherits_from_granted_dashboard(self):
        dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)
        insight = Insight.objects.create(team=self.team, name="i", created_by=self.user)
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)
        GuestResourceGrant.objects.create(
            organization_membership=self.membership,
            team=self.team,
            resource=GuestResourceGrant.Resource.DASHBOARD,
            resource_id=dashboard.id,
            is_pending=False,
        )
        self.assertEqual(self.uac.access_level_for_object(insight), "viewer")
