from posthog.test.base import APIBaseTest

from posthog.constants import AvailableFeature
from posthog.models import GuestResourceGrant, OrganizationInvite, OrganizationMembership, User

from products.dashboards.backend.models.dashboard import Dashboard


class TestPromoteToMember(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Ensure the requesting user is an admin
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )

    def test_admin_can_promote_guest_to_regular_member(self):
        guest_user = User.objects.create_user(email="gp@x.com", password="x", first_name="GP")
        guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=guest_user, is_guest=True
        )
        dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)
        GuestResourceGrant.objects.create(
            organization_membership=guest_membership,
            team=self.team,
            resource="dashboard",
            resource_id=dashboard.id,
            is_pending=False,
        )
        response = self.client.post(f"/api/organizations/@current/members/{guest_user.uuid}/promote_to_member/")
        self.assertEqual(response.status_code, 200, response.json())
        body = response.json()
        self.assertTrue(body["promoted"])
        self.assertEqual(body["grants_removed"], 1)
        guest_membership.refresh_from_db()
        self.assertFalse(guest_membership.is_guest)
        self.assertFalse(GuestResourceGrant.objects.filter(organization_membership=guest_membership).exists())

    def test_promote_rejects_already_regular_member(self):
        regular = User.objects.create_user(email="reg@x.com", password="x", first_name="R")
        OrganizationMembership.objects.create(organization=self.organization, user=regular, is_guest=False)
        response = self.client.post(f"/api/organizations/@current/members/{regular.uuid}/promote_to_member/")
        self.assertEqual(response.status_code, 400)

    def test_promote_requires_admin(self):
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(
            level=OrganizationMembership.Level.MEMBER
        )
        guest_user = User.objects.create_user(email="gpm@x.com", password="x", first_name="GPM")
        OrganizationMembership.objects.create(organization=self.organization, user=guest_user, is_guest=True)
        response = self.client.post(f"/api/organizations/@current/members/{guest_user.uuid}/promote_to_member/")
        self.assertIn(response.status_code, (403, 400))


class TestOrganizationInviteGuestFlow(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"},
        ]
        self.organization.save()
        # Ensure the requesting user is an admin
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )

    def test_admin_can_create_guest_invite_with_grants(self):
        dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": "guest@external.com",
                "is_guest": True,
                "bypass_sso_enforcement": False,
                "grants": [{"team_id": self.team.id, "resource": "dashboard", "resource_id": dashboard.id}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.json())
        invite_id = response.json()["id"]
        self.assertTrue(
            GuestResourceGrant.objects.filter(
                invite_id=invite_id,
                team=self.team,
                resource="dashboard",
                resource_id=dashboard.id,
                is_pending=True,
            ).exists()
        )

    def test_guest_invite_rejected_without_grants(self):
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {"target_email": "g@x.com", "is_guest": True, "grants": []},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_bypass_sso_without_acknowledgement_rejected(self):
        dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": "g@x.com",
                "is_guest": True,
                "bypass_sso_enforcement": True,
                "grants": [{"team_id": self.team.id, "resource": "dashboard", "resource_id": dashboard.id}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_bypass_sso_with_acknowledgement_accepted(self):
        dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": "g@x.com",
                "is_guest": True,
                "bypass_sso_enforcement": True,
                "bypass_acknowledged": True,
                "grants": [{"team_id": self.team.id, "resource": "dashboard", "resource_id": dashboard.id}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def test_existing_regular_member_cannot_be_invited_as_guest(self):
        existing = User.objects.create_user(email="existing@x.com", password="x", first_name="E")
        OrganizationMembership.objects.create(organization=self.organization, user=existing, is_guest=False)
        dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": "existing@x.com",
                "is_guest": True,
                "grants": [{"team_id": self.team.id, "resource": "dashboard", "resource_id": dashboard.id}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_org_lacking_ACCESS_CONTROL_rejects_guest_invite(self):
        self.organization.available_product_features = []
        self.organization.save()
        dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)
        response = self.client.post(
            "/api/organizations/@current/invites/",
            {
                "target_email": "g@x.com",
                "is_guest": True,
                "grants": [{"team_id": self.team.id, "resource": "dashboard", "resource_id": dashboard.id}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_invite_accept_creates_guest_membership_and_flips_grants(self):
        dashboard = Dashboard.objects.create(team=self.team, name="d", created_by=self.user)
        invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="new@x.com",
            is_guest=True,
        )
        GuestResourceGrant.objects.create(
            invite=invite,
            team=self.team,
            resource="dashboard",
            resource_id=dashboard.id,
            is_pending=True,
        )
        new_user = User.objects.create_user(email="new@x.com", password="x", first_name="N")
        invite.use(new_user, prevalidated=True)

        membership = OrganizationMembership.objects.get(organization=self.organization, user=new_user)
        self.assertTrue(membership.is_guest)

        grant = GuestResourceGrant.objects.get(organization_membership=membership)
        self.assertFalse(grant.is_pending)
        self.assertIsNone(grant.invite)
        self.assertEqual(grant.resource_id, dashboard.id)
