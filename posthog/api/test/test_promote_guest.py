from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import OrganizationMembership
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.user import User
from posthog.rbac.guest_grants import create_grant

from products.dashboards.backend.models.dashboard import Dashboard

from ee.models.rbac.access_control import AccessControl


class TestPromoteGuest(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self.guest_user = User.objects.create_user(
            email="guest@example.com", first_name="Guest", password="password123"
        )
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user, is_guest=True
        )
        dashboard = Dashboard.objects.create(team=self.team, name="Granted")
        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="dashboard",
            resource_id=str(dashboard.pk),
            created_by=self.user,
        )

    def _promote_url(self, membership: OrganizationMembership) -> str:
        return f"/api/organizations/{self.organization.id}/members/{membership.user.uuid}/promote_guest/"

    def test_non_admin_cannot_promote_guest(self) -> None:
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(
            level=OrganizationMembership.Level.MEMBER
        )
        res = self.client.post(self._promote_url(self.guest_membership))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_promotes_guest_removes_grants_and_flips_flag(self) -> None:
        res = self.client.post(self._promote_url(self.guest_membership))
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.guest_membership.refresh_from_db()
        self.assertFalse(self.guest_membership.is_guest)
        self.assertEqual(res.json()["removed_grants"], 1)

        self.assertFalse(
            AccessControl.objects.filter(
                organization_member=self.guest_membership,
                resource="dashboard",
            ).exists()
        )

    def test_promote_writes_activity_log(self) -> None:
        self.client.post(self._promote_url(self.guest_membership))
        self.assertTrue(
            ActivityLog.objects.filter(
                scope="OrganizationMembership",
                activity="promoted_from_guest",
                item_id=str(self.guest_membership.id),
            ).exists()
        )

    def test_promote_resets_bypass_sso(self) -> None:
        self.guest_membership.bypass_sso = True
        self.guest_membership.save(update_fields=["bypass_sso"])

        res = self.client.post(self._promote_url(self.guest_membership))
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)

        self.guest_membership.refresh_from_db()
        self.assertFalse(self.guest_membership.is_guest)
        self.assertFalse(self.guest_membership.bypass_sso)
