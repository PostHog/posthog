"""Coverage for the guest-specific fields of the `UserSerializer` payload.

`/api/users/@me/` carries `is_guest_in_current_project` and `guest_grants` so the FE
landing scene can render. These tests pin the shape of `guest_grants` — particularly
the `resource_name` field that powers the human-readable card label — and the
visibility rules that ensure non-guest payloads stay clean.
"""

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership
from posthog.models.insight import Insight
from posthog.models.user import User
from posthog.rbac.guest_grants import create_grant

from products.dashboards.backend.models.dashboard import Dashboard
from products.notebooks.backend.models import Notebook


class TestUserGuestPayload(APIBaseTest):
    """`/api/users/@me/` for a guest member surfaces every grant with display metadata."""

    def setUp(self) -> None:
        super().setUp()
        # ACCESS_CONTROL is the gate that flips AC-row resolution on; without it the
        # default access level path bypasses the guest-aware branches entirely.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"}
        ]
        self.organization.save()

        self.guest_user = User.objects.create_user(
            email="grant-payload-guest@example.com", first_name="Guest", password="password123"
        )
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user, is_guest=True
        )
        self.guest_user.current_organization = self.organization
        self.guest_user.current_team = self.team
        self.guest_user.save()

    def _payload(self) -> dict:
        self.client.force_login(self.guest_user)
        res = self.client.get("/api/users/@me/")
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        return res.json()

    def test_dashboard_grant_carries_resource_name(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="Q4 KPIs")
        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="dashboard",
            resource_id=str(dashboard.pk),
            created_by=self.user,
            access_level="viewer",
        )
        grants = self._payload()["guest_grants"]
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0]["resource"], "dashboard")
        self.assertEqual(grants[0]["resource_id_url"], str(dashboard.pk))
        self.assertEqual(grants[0]["resource_name"], "Q4 KPIs")

    def test_insight_grant_carries_name_and_short_id(self) -> None:
        insight = Insight.objects.create(team=self.team, name="Activation funnel", short_id="ACTIV001")
        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="insight",
            resource_id=insight.short_id,
            created_by=self.user,
            access_level="viewer",
        )
        grants = self._payload()["guest_grants"]
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0]["resource"], "insight")
        self.assertEqual(grants[0]["resource_id_url"], "ACTIV001")
        self.assertEqual(grants[0]["resource_name"], "Activation funnel")

    def test_insight_grant_falls_back_to_derived_name(self) -> None:
        # Saved insights without an explicit name surface their `derived_name` (e.g. the auto-
        # generated "$pageview total volume"). The payload must prefer name → derived_name → null.
        insight = Insight.objects.create(team=self.team, name="", derived_name="$pageview totals", short_id="DRVD0001")
        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="insight",
            resource_id=insight.short_id,
            created_by=self.user,
            access_level="viewer",
        )
        grants = self._payload()["guest_grants"]
        self.assertEqual(grants[0]["resource_name"], "$pageview totals")

    def test_notebook_grant_carries_title_and_short_id(self) -> None:
        notebook = Notebook.objects.create(team=self.team, title="Onboarding playbook", short_id="NBOOK001")
        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="notebook",
            resource_id=notebook.short_id,
            created_by=self.user,
            access_level="viewer",
        )
        grants = self._payload()["guest_grants"]
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0]["resource"], "notebook")
        self.assertEqual(grants[0]["resource_id_url"], "NBOOK001")
        self.assertEqual(grants[0]["resource_name"], "Onboarding playbook")

    def test_dashboard_with_unnamed_target_returns_empty_string_name(self) -> None:
        # Dashboard.name is a CharField with default="" — falsy but not None. The serializer
        # surfaces it as-is so the FE can decide whether to fall back to the resource id.
        dashboard = Dashboard.objects.create(team=self.team, name="")
        create_grant(
            membership=self.guest_membership,
            team=self.team,
            resource="dashboard",
            resource_id=str(dashboard.pk),
            created_by=self.user,
            access_level="viewer",
        )
        grants = self._payload()["guest_grants"]
        self.assertEqual(grants[0]["resource_name"], "")

    def test_non_guest_user_returns_empty_grants(self) -> None:
        # Regular members must never get a `guest_grants` array populated, even if AC rows
        # somehow exist on their membership.
        self.client.force_login(self.user)
        res = self.client.get("/api/users/@me/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json()["guest_grants"], [])
        self.assertFalse(res.json()["is_guest_in_current_project"])

    def test_guest_team_field_redacts_admin_only_metadata(self) -> None:
        # /api/users/@me/ embeds the user's current team via TeamBasicSerializer, which
        # exposes the team's `api_token` (write key) and onboarding flags. Guests must
        # not see those fields — the same redactor that runs over `organization.teams[]`
        # has to apply here too.
        from posthog.rbac.guest_access_policy import GUEST_REDACTED_TEAM_FIELDS

        team_payload = self._payload()["team"]
        for redacted in GUEST_REDACTED_TEAM_FIELDS:
            self.assertNotIn(redacted, team_payload, f"{redacted} leaked to guest payload")
        # Display fields the FE relies on must remain.
        self.assertEqual(team_payload["id"], self.team.id)
        self.assertEqual(team_payload["name"], self.team.name)

    def test_regular_member_team_field_keeps_admin_metadata(self) -> None:
        # Regression guard: redaction is guest-only. A regular member loading their own
        # @me payload must still receive the team's api_token (the FE bootstraps the
        # capture client from this field).
        self.client.force_login(self.user)
        res = self.client.get("/api/users/@me/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        team_payload = res.json()["team"]
        self.assertIn("api_token", team_payload)
        self.assertEqual(team_payload["api_token"], self.team.api_token)
