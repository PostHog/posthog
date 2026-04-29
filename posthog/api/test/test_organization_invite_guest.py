from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationInvite, OrganizationMembership
from posthog.models.user import User

from products.notebooks.backend.models import Notebook

from ee.models.rbac.access_control import AccessControl


class TestOrganizationInviteGuest(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"}
        ]
        self.organization.save()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self.notebook = Notebook.objects.create(team=self.team, title="Granted notebook", short_id="INVT0001")

    def _base_payload(self, **overrides) -> dict:
        payload = {
            "target_email": "newguest@example.com",
            "send_email": False,
            "guest_resources": [
                {
                    "team_id": self.team.pk,
                    "resource": "notebook",
                    "resource_id": self.notebook.short_id,
                }
            ],
        }
        payload.update(overrides)
        return payload

    def test_non_admin_cannot_create_guest_invite(self) -> None:
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(
            level=OrganizationMembership.Level.MEMBER
        )
        res = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            self._base_payload(),
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_access_control_feature_required(self) -> None:
        self.organization.available_product_features = []
        self.organization.save()
        res = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            self._base_payload(),
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Advanced permissions", res.json()["detail"])

    def test_nonexistent_resource_id_is_rejected(self) -> None:
        res = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            self._base_payload(
                guest_resources=[{"team_id": self.team.pk, "resource": "notebook", "resource_id": "ZZZZZZZZ"}]
            ),
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_editor_level_grants_are_rejected(self) -> None:
        # Editor-level guest grants are blocked at the invite API today. The data model and
        # service layer still accept editor (covered by `test_guest_grants.py`), but the
        # public surface refuses until the edit-grants admin flow ships.
        payload = self._base_payload(
            guest_resources=[
                {
                    "team_id": self.team.pk,
                    "resource": "notebook",
                    "resource_id": self.notebook.short_id,
                    "access_level": "editor",
                }
            ]
        )
        res = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            payload,
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertIn("Editor-level guest grants are not yet supported", res.content.decode())

    def test_admin_can_create_guest_invite(self) -> None:
        res = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            self._base_payload(bypass_sso=True),
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        invite = OrganizationInvite.objects.get(id=res.json()["id"])
        self.assertTrue(invite.is_guest_invite)
        self.assertTrue(invite.bypass_sso)
        self.assertEqual(len(invite.guest_resources), 1)

    def test_accepting_guest_invite_creates_membership_grants_and_access_controls(self) -> None:
        # Create invite as admin, then accept as a fresh user.
        res = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            self._base_payload(),
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        invite = OrganizationInvite.objects.get(id=res.json()["id"])

        invitee = User.objects.create_user(email="newguest@example.com", first_name="New Guest", password="password123")
        invite.use(invitee)

        membership = OrganizationMembership.objects.get(organization=self.organization, user=invitee)
        self.assertTrue(membership.is_guest)

        self.assertTrue(
            AccessControl.objects.filter(
                organization_member=membership,
                resource="notebook",
                resource_id=str(self.notebook.pk),
                access_level="viewer",
            ).exists()
        )

    def test_regular_invite_does_not_create_guest_membership(self) -> None:
        payload = {"target_email": "regular@example.com", "send_email": False}
        res = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            payload,
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        invite = OrganizationInvite.objects.get(id=res.json()["id"])

        invitee = User.objects.create_user(email="regular@example.com", first_name="Regular", password="password123")
        invite.use(invitee)

        membership = OrganizationMembership.objects.get(organization=self.organization, user=invitee)
        self.assertFalse(membership.is_guest)
        self.assertFalse(AccessControl.objects.filter(organization_member=membership).exists())

    def test_accepting_invite_with_bypass_sso_sets_membership_flag(self) -> None:
        res = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            self._base_payload(bypass_sso=True),
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        invite = OrganizationInvite.objects.get(id=res.json()["id"])
        invitee = User.objects.create_user(email="newguest@example.com", first_name="G", password="password123")
        invite.use(invitee)

        membership = OrganizationMembership.objects.get(organization=self.organization, user=invitee)
        self.assertTrue(membership.is_guest)
        self.assertTrue(membership.bypass_sso)

    def test_accepting_invite_without_bypass_sso_leaves_membership_flag_false(self) -> None:
        res = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            self._base_payload(),
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        invite = OrganizationInvite.objects.get(id=res.json()["id"])
        invitee = User.objects.create_user(email="newguest@example.com", first_name="G", password="password123")
        invite.use(invitee)

        membership = OrganizationMembership.objects.get(organization=self.organization, user=invitee)
        self.assertTrue(membership.is_guest)
        self.assertFalse(membership.bypass_sso)

    def test_bypass_sso_without_guest_resources_is_rejected(self) -> None:
        res = self.client.post(
            f"/api/organizations/{self.organization.id}/invites/",
            {"target_email": "regular@example.com", "send_email": False, "bypass_sso": True},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("bypass_sso", res.json()["attr"] or res.json().get("detail", ""))
