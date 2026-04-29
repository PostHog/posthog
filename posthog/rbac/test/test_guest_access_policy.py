from typing import cast

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import OrganizationMembership
from posthog.models.user import User
from posthog.rbac.guest_access_policy import (
    GUEST_FRAME_LEVEL_RESOURCES,
    GUEST_GRANTABLE_RESOURCES,
    GUEST_REDACTED_TEAM_FIELDS,
    filter_and_sanitize_teams_for_guest_access,
    guest_effective_team_membership_level,
    guest_object_access_level,
    guest_resource_access_level,
    redact_team_for_guest,
)
from posthog.rbac.user_access_control import NO_ACCESS_LEVEL, default_access_level
from posthog.scopes import APIScopeObject

from products.dashboards.backend.models.dashboard import Dashboard

from ee.models.rbac.access_control import AccessControl


class TestGuestAccessPolicyConstants(BaseTest):
    def test_grantable_resources_set(self):
        self.assertEqual(GUEST_GRANTABLE_RESOURCES, frozenset({"dashboard", "insight", "notebook"}))

    def test_frame_level_resources_set_excludes_plugin(self):
        # Plugin is intentionally NOT in this set — guests don't access plugin endpoints today
        # and we don't want to widen the surface preemptively.
        self.assertNotIn("plugin", GUEST_FRAME_LEVEL_RESOURCES)
        self.assertIn("project", GUEST_FRAME_LEVEL_RESOURCES)

    def test_redacted_team_fields_includes_api_token(self):
        self.assertIn("api_token", GUEST_REDACTED_TEAM_FIELDS)


class TestGuestObjectAccessLevel(BaseTest):
    def test_per_object_resource_returns_no_access(self):
        # Resources that have per-object AC rows: deny by default for guests.
        for resource in ("dashboard", "insight", "notebook", "feature_flag"):
            self.assertEqual(
                guest_object_access_level(resource, explicit=False),
                NO_ACCESS_LEVEL,
                msg=f"resource={resource}",
            )

    def test_per_object_resource_explicit_returns_none(self):
        self.assertIsNone(guest_object_access_level("dashboard", explicit=True))

    def test_frame_level_resource_falls_through_to_default(self):
        # Project = frame-level → guest gets the regular default (so the project shell renders).
        self.assertEqual(
            guest_object_access_level("project", explicit=False),
            default_access_level("project"),
        )

    def test_frame_level_resource_explicit_returns_none(self):
        self.assertIsNone(guest_object_access_level("project", explicit=True))

    def test_plugin_is_not_treated_as_frame_level(self):
        # Symmetric with the constants test: plugin is NOT in the carve-out, so a guest
        # asked about plugin gets deny-by-default like any other per-object resource.
        self.assertEqual(
            guest_object_access_level("plugin", explicit=False),
            NO_ACCESS_LEVEL,
        )


class TestGuestResourceAccessLevel(BaseTest):
    @parameterized.expand(
        [
            ("dashboard",),
            ("insight",),
            ("notebook",),
            ("project",),
            ("feature_flag",),
        ]
    )
    def test_always_returns_no_access(self, resource: str):
        # Resource-level access for a guest is always "deny." Any actual grant is per-object.
        self.assertEqual(guest_resource_access_level(cast("APIScopeObject", resource)), NO_ACCESS_LEVEL)


class TestGuestEffectiveTeamMembershipLevel(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.guest_user = User.objects.create_user(email="g@policy.com", password="pw", first_name="G")
        self.guest_membership = OrganizationMembership.objects.create(
            organization=self.organization, user=self.guest_user, is_guest=True
        )

    def test_returns_member_when_guest_has_grant_on_team(self):
        d = Dashboard.objects.create(team=self.team, name="D")
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id=str(d.id),
            organization_member=self.guest_membership,
            access_level="viewer",
            created_by=self.user,
        )
        self.assertEqual(
            guest_effective_team_membership_level(self.guest_membership, self.team.id),
            OrganizationMembership.Level.MEMBER,
        )

    def test_returns_none_when_guest_has_no_grant_on_team(self):
        self.assertIsNone(guest_effective_team_membership_level(self.guest_membership, self.team.id))

    def test_returns_none_for_grants_on_different_team(self):
        # Grant on a different team shouldn't grant frame access on this team.
        from posthog.models.team.team import Team

        other_team = Team.objects.create(organization=self.organization, name="other")
        d = Dashboard.objects.create(team=other_team, name="D")
        AccessControl.objects.create(
            team=other_team,
            resource="dashboard",
            resource_id=str(d.id),
            organization_member=self.guest_membership,
            access_level="viewer",
            created_by=self.user,
        )
        self.assertIsNone(guest_effective_team_membership_level(self.guest_membership, self.team.id))

    @parameterized.expand([("dashboard",), ("insight",), ("notebook",)])
    def test_any_grantable_resource_counts_as_membership(self, resource: str):
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id="42",
            organization_member=self.guest_membership,
            access_level="viewer",
            created_by=self.user,
        )
        self.assertEqual(
            guest_effective_team_membership_level(self.guest_membership, self.team.id),
            OrganizationMembership.Level.MEMBER,
        )


class TestFilterAndSanitizeTeamsForGuestAccess(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.guest_user = User.objects.create_user(email="g-sanitize@policy.com", password="pw", first_name="G")
        OrganizationMembership.objects.create(organization=self.organization, user=self.guest_user, is_guest=True)

    def _payload(self) -> list[dict]:
        return [
            {
                "id": self.team.id,
                "name": self.team.name,
                "api_token": "phc_secret",
                "completed_snippet_onboarding": True,
                "has_completed_onboarding_for": {"product_analytics": True},
                "ingested_event": True,
                "is_demo": False,
            }
        ]

    def test_strips_sensitive_fields_for_guest(self):
        result = filter_and_sanitize_teams_for_guest_access(self.organization, self.guest_user, self._payload())
        self.assertEqual(len(result), 1)
        for redacted in GUEST_REDACTED_TEAM_FIELDS:
            self.assertNotIn(redacted, result[0])
        self.assertEqual(result[0]["id"], self.team.id)
        self.assertEqual(result[0]["name"], self.team.name)

    def test_passthrough_for_regular_member(self):
        result = filter_and_sanitize_teams_for_guest_access(self.organization, self.user, self._payload())
        self.assertEqual(result[0]["api_token"], "phc_secret")
        self.assertTrue(result[0]["ingested_event"])

    def test_passthrough_for_anonymous_or_no_user(self):
        self.assertEqual(
            filter_and_sanitize_teams_for_guest_access(self.organization, None, self._payload()),
            self._payload(),
        )

    def test_passthrough_for_user_not_in_org(self):
        outsider = User.objects.create_user(email="outsider-policy@example.com", password="pw", first_name="O")
        result = filter_and_sanitize_teams_for_guest_access(self.organization, outsider, self._payload())
        self.assertEqual(result[0]["api_token"], "phc_secret")


class TestRedactTeamForGuest(BaseTest):
    """Single-team-payload variant of the team sanitizer, used by `UserSerializer.team`
    where the redactor isn't piped through `OrganizationSerializer.get_teams`."""

    def setUp(self) -> None:
        super().setUp()
        self.guest_user = User.objects.create_user(email="g-redact-team@policy.com", password="pw", first_name="G")
        OrganizationMembership.objects.create(organization=self.organization, user=self.guest_user, is_guest=True)

    def _payload(self) -> dict:
        return {
            "id": self.team.id,
            "uuid": str(self.team.uuid),
            "organization": str(self.organization.id),
            "name": self.team.name,
            "api_token": "phc_secret",
            "completed_snippet_onboarding": True,
            "has_completed_onboarding_for": {"product_analytics": True},
            "ingested_event": True,
            "is_demo": False,
        }

    def _request_for(self, user: "User | None"):
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = user  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        # Prime the guest cache the way the middleware does — keeps the helper
        # off the ORM in the hot path.
        from posthog.rbac.guest_request_cache import get_user_guest_org_ids

        get_user_guest_org_ids(request)
        return request

    def test_strips_sensitive_fields_for_guest(self):
        result = redact_team_for_guest(self._payload(), self._request_for(self.guest_user))
        assert result is not None
        for redacted in GUEST_REDACTED_TEAM_FIELDS:
            self.assertNotIn(redacted, result)
        self.assertEqual(result["id"], self.team.id)
        self.assertEqual(result["name"], self.team.name)

    def test_passthrough_for_regular_member(self):
        result = redact_team_for_guest(self._payload(), self._request_for(self.user))
        assert result is not None
        self.assertEqual(result["api_token"], "phc_secret")
        self.assertTrue(result["ingested_event"])

    def test_passthrough_when_request_is_none(self):
        # Guard against callers that hand the helper a serializer payload outside a
        # request context (e.g. a management command). No request → no guest decision.
        self.assertEqual(redact_team_for_guest(self._payload(), None), self._payload())

    def test_passthrough_when_payload_missing_organization(self):
        # The helper needs the team's org id to scope the is_guest check. If the caller
        # passes a payload that didn't serialize `organization`, fall through rather than
        # leaking guest-state to the wrong org.
        payload = self._payload()
        del payload["organization"]
        self.assertEqual(redact_team_for_guest(payload, self._request_for(self.guest_user)), payload)

    def test_passthrough_for_non_dict_payload(self):
        self.assertIsNone(redact_team_for_guest(None, self._request_for(self.guest_user)))

    def test_passthrough_when_user_is_guest_in_other_org_only(self):
        # User is a guest in `other_org` but a regular member of `self.organization`.
        # The team payload's `organization` points at `self.organization`, so the helper
        # must NOT redact — they're a regular member there.
        from posthog.models.organization import Organization

        other_org = Organization.objects.create(name="Other org")
        cross_user = User.objects.create_user(email="cross-org@policy.com", password="pw", first_name="X")
        OrganizationMembership.objects.create(organization=self.organization, user=cross_user, is_guest=False)
        OrganizationMembership.objects.create(organization=other_org, user=cross_user, is_guest=True)
        result = redact_team_for_guest(self._payload(), self._request_for(cross_user))
        assert result is not None
        self.assertEqual(result["api_token"], "phc_secret")
