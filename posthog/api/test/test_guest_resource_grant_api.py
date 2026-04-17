from posthog.test.base import APIBaseTest

from posthog.constants import AvailableFeature
from posthog.models import GuestResourceGrant, OrganizationMembership, User

from products.dashboards.backend.models.dashboard import Dashboard


class TestGuestResourceGrantAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"},
        ]
        self.organization.save()
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self.guest_user = User.objects.create_user(email="g@x.com", password="x", first_name="G")
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user, is_guest=True
        )
        self.dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)

    def _url(self, *extra):
        base = f"/api/organizations/@current/members/{self.guest_user.uuid}/grants/"
        return base + ("/".join(str(x) for x in extra) + "/" if extra else "")

    def test_admin_can_list_grants(self):
        GuestResourceGrant.objects.create(
            organization_membership=self.guest_membership,
            team=self.team,
            resource="dashboard",
            resource_id=self.dashboard.id,
            is_pending=False,
        )
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_admin_can_create_grant(self):
        response = self.client.post(
            self._url(),
            {"team_id": self.team.id, "resource": "dashboard", "resource_id": self.dashboard.id},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.json())
        self.assertTrue(
            GuestResourceGrant.objects.filter(
                organization_membership=self.guest_membership,
                resource="dashboard",
                resource_id=self.dashboard.id,
                is_pending=False,
            ).exists()
        )

    def test_admin_can_delete_grant(self):
        grant = GuestResourceGrant.objects.create(
            organization_membership=self.guest_membership,
            team=self.team,
            resource="dashboard",
            resource_id=self.dashboard.id,
            is_pending=False,
        )
        response = self.client.delete(self._url(grant.id))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(GuestResourceGrant.objects.filter(id=grant.id).exists())

    def test_non_admin_cannot_list_grants(self):
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.MEMBER
        )
        response = self.client.get(self._url())
        self.assertIn(response.status_code, (403, 400))

    def test_grant_create_rejects_non_guest_target(self):
        regular = User.objects.create_user(email="r@x.com", password="x", first_name="R")
        OrganizationMembership.objects.create(organization=self.organization, user=regular, is_guest=False)
        url = f"/api/organizations/@current/members/{regular.uuid}/grants/"
        response = self.client.post(
            url,
            {"team_id": self.team.id, "resource": "dashboard", "resource_id": self.dashboard.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
