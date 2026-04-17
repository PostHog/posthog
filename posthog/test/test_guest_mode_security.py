import json

from posthog.test.base import APIBaseTest

from posthog.constants import AvailableFeature
from posthog.models import GuestResourceGrant, OrganizationMembership, User

from products.dashboards.backend.models.dashboard import Dashboard


class TestGuestModeSecurity(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"},
        ]
        self.organization.save()

        self.guest = User.objects.create_user(email="g@x.com", password="x", first_name="G")
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest, is_guest=True
        )
        self.granted_dashboard = Dashboard.objects.create(team=self.team, name="granted", created_by=self.user)
        GuestResourceGrant.objects.create(
            organization_membership=self.guest_membership,
            team=self.team,
            resource="dashboard",
            resource_id=self.granted_dashboard.id,
            is_pending=False,
        )
        self.other_dashboard = Dashboard.objects.create(team=self.team, name="other", created_by=self.user)
        self.client.force_login(self.guest)

    def test_guest_cannot_access_non_granted_dashboard_via_api(self):
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.other_dashboard.id}/")
        self.assertIn(response.status_code, (403, 404))

    def test_guest_cannot_execute_arbitrary_hogql(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/query/",
            json.dumps({"query": {"kind": "HogQLQuery", "query": "SELECT 1"}}),
            content_type="application/json",
        )
        self.assertIn(response.status_code, (403, 404))

    def test_guest_cannot_access_data_warehouse(self):
        response = self.client.get(f"/api/projects/{self.team.id}/data_warehouse/")
        self.assertIn(response.status_code, (403, 404))

    def test_guest_cannot_access_feature_flags(self):
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/")
        self.assertIn(response.status_code, (403, 404))

    def test_guest_cannot_be_promoted_by_regular_member(self):
        regular = User.objects.create_user(email="reg@x.com", password="x", first_name="R")
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=regular,
            is_guest=False,
            level=OrganizationMembership.Level.MEMBER,
        )
        self.client.force_login(regular)
        response = self.client.post(f"/api/organizations/@current/members/{self.guest.uuid}/promote_to_member/")
        self.assertIn(response.status_code, (403, 400))

    def test_guest_sso_bypass_flag_persists(self):
        self.guest_membership.bypass_sso_enforcement = True
        self.guest_membership.save()
        self.guest_membership.refresh_from_db()
        self.assertTrue(self.guest_membership.bypass_sso_enforcement)
