from posthog.test.base import APIBaseTest

from django.core.cache import cache
from django.utils import timezone

from rest_framework import status

from posthog.models import Organization, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_invite import OrganizationInvite

from products.dashboards.backend.models.dashboard import Dashboard


class TestWelcomeEndpoint(APIBaseTest):
    def setUp(self):
        cache.clear()
        super().setUp()

    def test_returns_current_organization_name(self):
        response = self.client.get("/api/organizations/@current/welcome/current/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["organization_name"], self.organization.name)
        self.assertIn("team_members", data)
        self.assertIn("recent_activity", data)
        self.assertIn("popular_dashboards", data)
        self.assertIn("products_in_use", data)
        self.assertIn("suggested_next_steps", data)

    def test_empty_org_renders_empty_cards(self):
        response = self.client.get("/api/organizations/@current/welcome/current/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["team_members"], [])
        self.assertEqual(data["recent_activity"], [])
        self.assertEqual(data["popular_dashboards"], [])
        # Always falls back to at least one suggested step.
        self.assertGreaterEqual(len(data["suggested_next_steps"]), 1)

    def test_inviter_returned_from_invited_by_on_membership(self):
        """Primary inviter path: persisted on the membership when the invite was accepted."""
        founder = User.objects.create_and_join(self.organization, "founder@example.com", None, "Founder")
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.invited_by = founder
        membership.save(update_fields=["invited_by"])

        response = self.client.get("/api/organizations/@current/welcome/current/")
        data = response.json()
        self.assertIsNotNone(data["inviter"])
        self.assertEqual(data["inviter"]["email"], founder.email)

    def test_inviter_falls_back_to_lingering_invite_row(self):
        """Fallback for pre-1102 memberships or legacy paths that didn't populate invited_by."""
        founder = User.objects.create_and_join(self.organization, "founder@example.com", None, "Founder")
        OrganizationInvite.objects.create(
            organization=self.organization,
            target_email=self.user.email,
            created_by=founder,
        )
        response = self.client.get("/api/organizations/@current/welcome/current/")
        data = response.json()
        self.assertIsNotNone(data["inviter"])
        self.assertEqual(data["inviter"]["email"], founder.email)

    def test_returns_teammates_excluding_self(self):
        other = User.objects.create_and_join(self.organization, "teammate@example.com", None, "Teammate")
        response = self.client.get("/api/organizations/@current/welcome/current/")
        data = response.json()
        emails = [m["email"] for m in data["team_members"]]
        self.assertIn(other.email, emails)
        self.assertNotIn(self.user.email, emails)

    def test_members_never_logged_in_show_never_status(self):
        User.objects.create_and_join(self.organization, "never@example.com", None, "Never")
        response = self.client.get("/api/organizations/@current/welcome/current/")
        data = response.json()
        never_member = next((m for m in data["team_members"] if m["email"] == "never@example.com"), None)
        assert never_member is not None
        self.assertEqual(never_member["last_active"], "never")

    def test_recent_activity_dedupes_by_item(self):
        ActivityLog.objects.create(
            team_id=self.team.id,
            organization_id=self.organization.id,
            scope="Insight",
            activity="updated",
            item_id="123",
            detail={"name": "My insight"},
            user=self.user,
            is_system=False,
            was_impersonated=False,
        )
        ActivityLog.objects.create(
            team_id=self.team.id,
            organization_id=self.organization.id,
            scope="Insight",
            activity="updated",
            item_id="123",
            detail={"name": "My insight"},
            user=self.user,
            is_system=False,
            was_impersonated=False,
        )
        response = self.client.get("/api/organizations/@current/welcome/current/")
        data = response.json()
        self.assertEqual(len(data["recent_activity"]), 1)
        self.assertEqual(data["recent_activity"][0]["entity_name"], "My insight")

    def test_recent_activity_truncates_long_entity_names(self):
        ActivityLog.objects.create(
            team_id=self.team.id,
            organization_id=self.organization.id,
            scope="Insight",
            activity="created",
            item_id="42",
            detail={"name": "x" * 5000},
            user=self.user,
            is_system=False,
            was_impersonated=False,
        )
        response = self.client.get("/api/organizations/@current/welcome/current/")
        data = response.json()
        self.assertEqual(len(data["recent_activity"][0]["entity_name"]), 200)

    def test_recent_activity_excludes_foreign_team_rows(self):
        """Rows from teams the user can't access (or teams outside this org) must not leak."""
        # Use a team id that doesn't belong to this org — we don't need a real Team row, the endpoint
        # only filters by team_id membership in the current org's team set.
        foreign_team_id = 9_999_999
        ActivityLog.objects.create(
            team_id=foreign_team_id,
            scope="Insight",
            activity="created",
            item_id="42",
            detail={"name": "Cross-org leak"},
            user=self.user,
            is_system=False,
            was_impersonated=False,
        )
        response = self.client.get("/api/organizations/@current/welcome/current/")
        data = response.json()
        entity_names = [item["entity_name"] for item in data["recent_activity"]]
        self.assertNotIn("Cross-org leak", entity_names)

    def test_popular_dashboards(self):
        dashboard = Dashboard.objects.create(team=self.team, name="Top dashboard")
        dashboard.last_accessed_at = timezone.now()
        dashboard.save()
        response = self.client.get("/api/organizations/@current/welcome/current/")
        data = response.json()
        self.assertEqual(len(data["popular_dashboards"]), 1)
        self.assertEqual(data["popular_dashboards"][0]["name"], "Top dashboard")

    def test_products_in_use_from_ingested_events(self):
        self.team.ingested_event = True
        self.team.save()
        response = self.client.get("/api/organizations/@current/welcome/current/")
        data = response.json()
        self.assertIn("product_analytics", data["products_in_use"])

    def test_is_organization_first_user_true_for_direct_signup(self):
        """Users who created the org (no inviter on their membership) are first users."""
        org = Organization.objects.create(name="Org-direct-signup")
        member = User.objects.create_and_join(org, "creator@example.com", "password")
        member.current_organization = org
        member.save()
        self.client.force_login(member)
        response = self.client.get("/api/users/@me/")
        self.assertTrue(response.json()["is_organization_first_user"])

    def test_is_organization_first_user_false_for_invitee(self):
        """Users whose membership has an invited_by FK (invite acceptance) are not first users."""
        org = Organization.objects.create(name="Org-invitee")
        creator = User.objects.create_and_join(org, "creator-invitee@example.com", "password")
        invitee = User.objects.create_and_join(org, "invitee@example.com", "password")
        # Simulate that this user arrived via OrganizationInvite.use() — i.e. invited_by is populated.
        OrganizationMembership.objects.filter(organization=org, user=invitee).update(invited_by=creator)
        invitee.current_organization = org
        invitee.save()
        self.client.force_login(invitee)
        response = self.client.get("/api/users/@me/")
        self.assertFalse(response.json()["is_organization_first_user"])

    def test_unauthenticated_cannot_access_welcome(self):
        self.client.logout()
        response = self.client.get("/api/organizations/@current/welcome/current/")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
