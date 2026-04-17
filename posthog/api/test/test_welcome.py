from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized
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
        response = self.client.get("/api/organizations/@current/welcome/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["organization_name"], self.organization.name)
        self.assertIn("team_members", data)
        self.assertIn("recent_activity", data)
        self.assertIn("popular_dashboards", data)
        self.assertIn("products_in_use", data)
        self.assertIn("suggested_next_steps", data)

    def test_empty_org_renders_empty_cards(self):
        response = self.client.get("/api/organizations/@current/welcome/")
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

        response = self.client.get("/api/organizations/@current/welcome/")
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
        response = self.client.get("/api/organizations/@current/welcome/")
        data = response.json()
        self.assertIsNotNone(data["inviter"])
        self.assertEqual(data["inviter"]["email"], founder.email)

    def test_returns_teammates_excluding_self(self):
        other = User.objects.create_and_join(self.organization, "teammate@example.com", None, "Teammate")
        response = self.client.get("/api/organizations/@current/welcome/")
        data = response.json()
        emails = [m["email"] for m in data["team_members"]]
        self.assertIn(other.email, emails)
        self.assertNotIn(self.user.email, emails)

    def test_self_filter_is_case_insensitive(self):
        """A member whose email differs only in case from the requester should still be filtered out."""
        uppercase_self = User.objects.create_and_join(self.organization, self.user.email.upper(), None, "Other")
        # Should NOT appear in team_members since it matches self.user.email case-insensitively.
        response = self.client.get("/api/organizations/@current/welcome/")
        data = response.json()
        emails_lower = [(m["email"] or "").lower() for m in data["team_members"]]
        self.assertNotIn(self.user.email.lower(), emails_lower)
        # Cleanup
        uppercase_self.delete()

    def test_members_never_logged_in_show_never_status(self):
        User.objects.create_and_join(self.organization, "never@example.com", None, "Never")
        response = self.client.get("/api/organizations/@current/welcome/")
        data = response.json()
        never_member = next((m for m in data["team_members"] if m["email"] == "never@example.com"), None)
        self.assertIsNotNone(never_member)
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
        )
        response = self.client.get("/api/organizations/@current/welcome/")
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
        )
        response = self.client.get("/api/organizations/@current/welcome/")
        data = response.json()
        self.assertEqual(len(data["recent_activity"][0]["entity_name"]), 200)

    def test_recent_activity_excludes_foreign_team_rows(self):
        """Rows from teams the user can't access (or teams outside this org) must not leak."""
        other_org = Organization.objects.create(name="Other org")
        from posthog.models.team import Team

        foreign_team = Team.objects.create(organization=other_org, name="Foreign")
        ActivityLog.objects.create(
            team_id=foreign_team.id,
            organization_id=other_org.id,
            scope="Insight",
            activity="created",
            item_id="42",
            detail={"name": "Cross-org leak"},
            user=self.user,
            is_system=False,
        )
        response = self.client.get("/api/organizations/@current/welcome/")
        data = response.json()
        entity_names = [item["entity_name"] for item in data["recent_activity"]]
        self.assertNotIn("Cross-org leak", entity_names)

    def test_popular_dashboards(self):
        dashboard = Dashboard.objects.create(team=self.team, name="Top dashboard")
        dashboard.last_accessed_at = timezone.now()
        dashboard.save()
        response = self.client.get("/api/organizations/@current/welcome/")
        data = response.json()
        self.assertEqual(len(data["popular_dashboards"]), 1)
        self.assertEqual(data["popular_dashboards"][0]["name"], "Top dashboard")

    def test_products_in_use_from_ingested_events(self):
        self.team.ingested_event = True
        self.team.save()
        response = self.client.get("/api/organizations/@current/welcome/")
        data = response.json()
        self.assertIn("product_analytics", data["products_in_use"])

    @parameterized.expand(
        [
            # (name, is_first_joiner, expected_is_first_user)
            ("sole_member_is_first_user", True, True),
            ("second_joiner_is_not_first_user", False, False),
        ]
    )
    def test_is_organization_first_user(self, _name: str, is_first_joiner: bool, expected: bool):
        org = Organization.objects.create(name=f"Org-{_name}")
        first_member = User.objects.create_and_join(org, f"first-{_name}@example.com", "password")
        if is_first_joiner:
            member = first_member
        else:
            with freeze_time(timezone.now() + timedelta(seconds=1)):
                member = User.objects.create_and_join(org, f"second-{_name}@example.com", "password")
        self.client.force_login(member)
        member.current_organization = org
        member.save()
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.json()["is_organization_first_user"], expected)

    def test_is_organization_first_user_short_circuits_for_dismissed_users(self):
        """Once welcome_screen_seen_at is set, the field must be false to avoid the ordering query."""
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.welcome_screen_seen_at = timezone.now()
        membership.save(update_fields=["welcome_screen_seen_at", "updated_at"])
        response = self.client.get("/api/users/@me/")
        self.assertFalse(response.json()["is_organization_first_user"])

    def test_unauthenticated_cannot_access_welcome(self):
        self.client.logout()
        response = self.client.get("/api/organizations/@current/welcome/")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


class TestWelcomeScreenDismiss(APIBaseTest):
    def setUp(self):
        cache.clear()
        super().setUp()

    def test_dismiss_sets_seen_at(self):
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        self.assertIsNone(membership.welcome_screen_seen_at)

        response = self.client.post(f"/api/users/{self.user.uuid}/welcome_screen/dismiss/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.json()["welcome_screen_seen_at"])

        membership.refresh_from_db()
        self.assertIsNotNone(membership.welcome_screen_seen_at)

    def test_dismiss_is_idempotent(self):
        first = self.client.post(f"/api/users/{self.user.uuid}/welcome_screen/dismiss/")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        first_seen_at = first.json()["welcome_screen_seen_at"]

        second = self.client.post(f"/api/users/{self.user.uuid}/welcome_screen/dismiss/")
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.json()["welcome_screen_seen_at"], first_seen_at)

    def test_dismiss_via_me_alias(self):
        response = self.client.post("/api/users/@me/welcome_screen/dismiss/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cannot_dismiss_another_users_welcome_screen(self):
        """Non-staff users can't dismiss a different user's screen; staff users are also blocked by the @me check."""
        other = User.objects.create_and_join(self.organization, "other@example.com", None)
        # Non-staff path — get_object refuses to look up a non-@me user.
        self.user.is_staff = False
        self.user.save()
        response = self.client.post(f"/api/users/{other.uuid}/welcome_screen/dismiss/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Staff path — the action itself enforces @me only.
        self.user.is_staff = True
        self.user.save()
        response = self.client.post(f"/api/users/{other.uuid}/welcome_screen/dismiss/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        other_membership = OrganizationMembership.objects.get(user=other)
        self.assertIsNone(other_membership.welcome_screen_seen_at)

    def test_dismiss_scoped_per_org(self):
        other_org = Organization.objects.create(name="Second org")
        self.user.join(organization=other_org)
        # user.join mutates current_organization; put it back so the dismiss writes to the expected org.
        self.user.current_organization = self.organization
        self.user.save()

        self.client.post("/api/users/@me/welcome_screen/dismiss/")
        membership_current = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership_other = OrganizationMembership.objects.get(user=self.user, organization=other_org)

        self.assertIsNotNone(membership_current.welcome_screen_seen_at)
        self.assertIsNone(membership_other.welcome_screen_seen_at)

    def test_welcome_screen_seen_at_exposed_on_me(self):
        self.client.post(f"/api/users/{self.user.uuid}/welcome_screen/dismiss/")
        response = self.client.get("/api/users/@me/")
        self.assertIsNotNone(response.json()["welcome_screen_seen_at"])
