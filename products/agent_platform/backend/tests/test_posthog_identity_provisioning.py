"""
Promote provisions a managed PostHog identity OAuthApplication.

When a revision declares an identity provider of `{kind: posthog}`, promote
ensures a normal (user-consented, NOT first-party) OAuthApplication for the
agent's org and injects its client_id into the live spec. Idempotent across
re-promotes.
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest

from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from rest_framework import status

from posthog.models.oauth import OAuthApplication

from ..logic.posthog_identity_app import provision_posthog_identity_apps
from ..models import AgentApplication, AgentRevision

POSTHOG_SPEC = {
    "model": "anthropic/claude-sonnet-4-6",
    "identity_providers": [{"kind": "posthog", "id": "posthog", "scopes": ["user:read"]}],
}


@override_settings(AGENT_INGRESS_PUBLIC_URL="https://ingress.example.com")
class TestPostHogIdentityProvisioning(APIBaseTest):
    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def setUp(self) -> None:
        super().setUp()
        self.application = AgentApplication.all_teams.create(
            team_id=self.team.id, slug="dog-bot", name="Dog bot", description=""
        )

    def _ready_revision(self, spec: dict) -> AgentRevision:
        return AgentRevision.all_teams.create(
            application=self.application,
            team_id=self.team.id,
            state="ready",
            spec=spec,
            bundle_sha256="a" * 64,
        )

    def _promote(self, revision: AgentRevision) -> None:
        url = f"/api/projects/{self.team.id}/agent_applications/{self.application.id}/revisions/{revision.id}/promote/"
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)

    def _identity_apps(self) -> list[OAuthApplication]:
        return list(OAuthApplication.objects.filter(organization=self.organization, name__startswith="Agent identity"))

    def test_promote_provisions_normal_consented_app_and_injects_client_id(self) -> None:
        revision = self._ready_revision(POSTHOG_SPEC)
        self._promote(revision)

        apps = self._identity_apps()
        self.assertEqual(len(apps), 1)
        app = apps[0]
        # Normal app → user sees the consent screen (the whole point).
        self.assertFalse(app.is_first_party)
        self.assertEqual(app.client_type, OAuthApplication.CLIENT_PUBLIC)
        self.assertEqual(app.authorization_grant_type, OAuthApplication.GRANT_AUTHORIZATION_CODE)
        self.assertEqual(app.algorithm, "RS256")
        self.assertEqual(app.redirect_uris, "https://ingress.example.com/link/posthog/callback")
        self.assertEqual(list(app.scopes), ["user:read"])

        # The live spec carries the provisioned client_id for the runner.
        revision.refresh_from_db()
        entry = revision.spec["identity_providers"][0]
        self.assertEqual(entry["client_id"], app.client_id)

    def test_promote_is_idempotent_reuses_the_app(self) -> None:
        first = self._ready_revision(POSTHOG_SPEC)
        self._promote(first)
        first.refresh_from_db()
        client_id = first.spec["identity_providers"][0]["client_id"]

        second = self._ready_revision(POSTHOG_SPEC)
        self._promote(second)
        second.refresh_from_db()

        # Same org + agent + provider → one app, reused; same client_id.
        self.assertEqual(len(self._identity_apps()), 1)
        self.assertEqual(second.spec["identity_providers"][0]["client_id"], client_id)

    def test_promote_without_posthog_provider_provisions_nothing(self) -> None:
        revision = self._ready_revision({"model": "anthropic/claude-sonnet-4-6"})
        self._promote(revision)
        self.assertEqual(len(self._identity_apps()), 0)

    @override_settings(
        AGENT_INGRESS_ROUTING_MODE="domain",
        AGENT_INGRESS_DOMAIN_SUFFIX=".agents.us.posthog.com",
    )
    def test_domain_mode_registers_per_agent_callback_host(self) -> None:
        revision = self._ready_revision(POSTHOG_SPEC)
        self._promote(revision)

        app = self._identity_apps()[0]
        # In domain mode the callback lands on the agent's own env-specific host,
        # not a flat/shared one — this is the redirect that must match what the
        # runner sends at authorize time (build_link_callback_url mirror).
        self.assertEqual(app.redirect_uris, "https://dog-bot.agents.us.posthog.com/link/posthog/callback")

    @override_settings(AGENT_INGRESS_ROUTING_MODE="domain", AGENT_INGRESS_DOMAIN_SUFFIX="")
    def test_missing_callback_host_fails_loudly(self) -> None:
        revision = self._ready_revision(POSTHOG_SPEC)
        with self.assertRaises(ImproperlyConfigured):
            provision_posthog_identity_apps(application=self.application, revision=revision, acting_user=self.user)
