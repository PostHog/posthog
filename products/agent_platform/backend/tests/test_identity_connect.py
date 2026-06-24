"""
Owner-initiated CONNECT flow for agent-level (`binding: 'agent'`) identity
providers.

Two surfaces are covered:

  - The logic module `agent_identity_connect` (mint/list/revoke) directly,
    against the agent_platform product DB.
  - The `AgentApplicationViewSet` identity actions, which are all gated by
    `_require_team_admin` (non-admins get 404, not 403, so the surface is
    invisible to them).

The node-side token exchange + credential storage (`Oauth2AuthProvider.complete`
→ `putAgentScoped`) is covered by the agent-shared / agent-tests suites.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest

from django.conf import settings
from django.test import override_settings

from rest_framework import status

from posthog.models.organization import OrganizationMembership

from ..logic.agent_identity_connect import AgentConnectError, list_connections, mint_authorize_url, revoke_connection
from ..models import AgentApplication, AgentIdentityCredential, AgentIdentityLinkState, AgentRevision

_OAUTH2_AGENT_PROVIDER = {
    "kind": "oauth2",
    "id": "dogs",
    "binding": "agent",
    "acknowledge_shared_credential": True,
    "authorize_url": "https://dogs.example.com/oauth/authorize",
    "token_url": "https://dogs.example.com/oauth/token",
    "client_id": "dogs-client-id",
    "scopes": ["woof", "fetch"],
}
_POSTHOG_AGENT_PROVIDER = {
    "kind": "posthog",
    "id": "posthog",
    "binding": "agent",
    "acknowledge_shared_credential": True,
    "client_id": "ph-client-id",
    "scopes": ["openid"],
}
_PRINCIPAL_PROVIDER = {
    "kind": "oauth2",
    "id": "per-user",
    "binding": "principal",
    "authorize_url": "https://example.com/oauth/authorize",
    "token_url": "https://example.com/oauth/token",
    "client_id": "per-user-client-id",
}

_DATABASES = {
    "default",
    "persons_db_writer",
    "persons_db_reader",
    "agent_platform_db_writer",
    "agent_platform_db_reader",
}


class TestAgentIdentityConnectLogic(APIBaseTest):
    """Direct tests of the mint/list/revoke logic module."""

    databases = _DATABASES

    def setUp(self) -> None:
        super().setUp()
        self.application = AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug="connect-agent",
            name="Connect agent",
            description="",
        )

    def _set_live_spec(self, *providers: dict) -> AgentRevision:
        revision = AgentRevision.all_teams.create(
            application=self.application,
            team_id=self.team.id,
            state="live",
            spec={"model": "anthropic/claude-haiku-4-5", "identity_providers": list(providers)},
            bundle_uri="fs://connect-agent/",
            bundle_sha256="a" * 64,
        )
        self.application.live_revision = revision
        self.application.save()
        return revision

    # ── mint_authorize_url ──────────────────────────────────────────────

    def test_mint_oauth2_agent_provider(self) -> None:
        self._set_live_spec(_OAUTH2_AGENT_PROVIDER)

        url = mint_authorize_url(self.application, "dogs")

        parsed = urlparse(url)
        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", "https://dogs.example.com/oauth/authorize")
        qs = parse_qs(parsed.query)
        self.assertEqual(qs["response_type"], ["code"])
        self.assertEqual(qs["client_id"], ["dogs-client-id"])
        self.assertEqual(qs["code_challenge_method"], ["S256"])
        self.assertEqual(qs["scope"], ["woof fetch"])
        self.assertIn("code_challenge", qs)
        self.assertTrue(qs["code_challenge"][0])

        # A single agent-scoped link-state row was written.
        links = list(AgentIdentityLinkState.all_teams.filter(application_id=self.application.id))
        self.assertEqual(len(links), 1)
        link = links[0]
        self.assertIsNone(link.agent_user_id)
        self.assertEqual(link.provider, "dogs")
        self.assertTrue(link.code_verifier)
        self.assertEqual(link.scopes, ["woof", "fetch"])

        # `state` is the link-state row id; redirect_uri points at the ingress
        # callback for this provider and matches the persisted row.
        self.assertEqual(qs["state"], [str(link.id)])
        expected_redirect = f"{settings.AGENT_INGRESS_PUBLIC_URL.rstrip('/')}/link/dogs/callback"
        self.assertEqual(qs["redirect_uri"], [expected_redirect])
        self.assertEqual(link.redirect_uri, expected_redirect)

    def test_mint_posthog_agent_provider(self) -> None:
        self._set_live_spec(_POSTHOG_AGENT_PROVIDER)

        url = mint_authorize_url(self.application, "posthog")

        parsed = urlparse(url)
        self.assertEqual(
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
            f"{settings.SITE_URL.rstrip('/')}/oauth/authorize/",
        )
        qs = parse_qs(parsed.query)
        self.assertEqual(qs["client_id"], ["ph-client-id"])
        self.assertEqual(qs["code_challenge_method"], ["S256"])

        link = AgentIdentityLinkState.all_teams.get(application_id=self.application.id, provider="posthog")
        self.assertIsNone(link.agent_user_id)
        self.assertTrue(link.code_verifier)

    def test_mint_rejects_principal_bound_provider(self) -> None:
        self._set_live_spec(_PRINCIPAL_PROVIDER)
        with self.assertRaises(AgentConnectError):
            mint_authorize_url(self.application, "per-user")
        # No link-state row leaks on the rejection path.
        self.assertFalse(AgentIdentityLinkState.all_teams.filter(application_id=self.application.id).exists())

    def test_mint_rejects_unknown_provider(self) -> None:
        self._set_live_spec(_OAUTH2_AGENT_PROVIDER)
        with self.assertRaises(AgentConnectError):
            mint_authorize_url(self.application, "nope")

    def test_mint_rejects_without_live_revision(self) -> None:
        # Application has no live_revision pointer at all.
        self.assertIsNone(self.application.live_revision)
        with self.assertRaises(AgentConnectError):
            mint_authorize_url(self.application, "dogs")

    @override_settings(AGENT_INGRESS_PUBLIC_URL=None)
    def test_mint_requires_ingress_public_url(self) -> None:
        # No silent fallback to PostHog Cloud's ingress — a self-hosted instance
        # that forgot to set this must fail loudly, not register a Cloud redirect_uri.
        self._set_live_spec(_OAUTH2_AGENT_PROVIDER)
        with self.assertRaises(AgentConnectError):
            mint_authorize_url(self.application, "dogs")
        # And it fails before writing any link-state row.
        self.assertFalse(AgentIdentityLinkState.all_teams.filter(application_id=self.application.id).exists())

    def test_mint_is_idempotent_retiring_prior_live_rows(self) -> None:
        # A re-clicked connect retires the prior unused link-state row, so only the
        # latest is live — abandoned round-trips don't accumulate.
        self._set_live_spec(_OAUTH2_AGENT_PROVIDER)
        mint_authorize_url(self.application, "dogs")
        mint_authorize_url(self.application, "dogs")
        rows = AgentIdentityLinkState.all_teams.filter(application_id=self.application.id, provider="dogs")
        self.assertEqual(rows.count(), 2)
        self.assertEqual(rows.filter(used_at__isnull=True).count(), 1)

    # ── list_connections ────────────────────────────────────────────────

    def test_list_returns_only_agent_scoped_rows(self) -> None:
        agent_row = AgentIdentityCredential.all_teams.create(
            team_id=self.team.id,
            application_id=self.application.id,
            agent_user_id=None,
            provider="dogs",
            encrypted_credentials="ciphertext-secret",
            scopes=["woof"],
            state="active",
            subject="dog-subject",
        )
        # A per-principal row for the same app must NOT appear.
        AgentIdentityCredential.all_teams.create(
            team_id=self.team.id,
            application_id=self.application.id,
            agent_user_id="11111111-1111-4111-8111-111111111111",
            provider="github",
            encrypted_credentials="ciphertext-secret",
            state="active",
        )

        results = list_connections(self.application)

        self.assertEqual(len(results), 1)
        row = results[0]
        self.assertEqual(row["provider"], "dogs")
        self.assertEqual(row["state"], "active")
        self.assertEqual(row["scopes"], ["woof"])
        self.assertEqual(row["subject"], "dog-subject")
        # Never the encrypted credential material.
        self.assertNotIn("encrypted_credentials", row)
        self.assertNotIn("ciphertext-secret", str(row))
        self.assertEqual(row["created_at"], agent_row.created_at.isoformat())

    # ── revoke_connection ───────────────────────────────────────────────

    def test_revoke_flips_active_agent_scoped_row(self) -> None:
        cred = AgentIdentityCredential.all_teams.create(
            team_id=self.team.id,
            application_id=self.application.id,
            agent_user_id=None,
            provider="dogs",
            encrypted_credentials="ciphertext",
            state="active",
        )
        self.assertTrue(revoke_connection(self.application, "dogs"))
        cred.refresh_from_db()
        self.assertEqual(cred.state, "revoked")
        self.assertIsNotNone(cred.revoked_at)

    def test_revoke_returns_false_when_nothing_active(self) -> None:
        self.assertFalse(revoke_connection(self.application, "dogs"))
        # An already-revoked row is not "active" → still False.
        AgentIdentityCredential.all_teams.create(
            team_id=self.team.id,
            application_id=self.application.id,
            agent_user_id=None,
            provider="dogs",
            encrypted_credentials="ciphertext",
            state="revoked",
        )
        self.assertFalse(revoke_connection(self.application, "dogs"))


class TestAgentIdentityConnectViewsetAuth(APIBaseTest):
    """The viewset identity actions are owner/team-admin only (`_require_team_admin`)."""

    databases = _DATABASES

    def setUp(self) -> None:
        super().setUp()
        self.application = AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug="connect-auth-agent",
            name="Connect auth agent",
            description="",
        )
        revision = AgentRevision.all_teams.create(
            application=self.application,
            team_id=self.team.id,
            state="live",
            spec={"identity_providers": [_OAUTH2_AGENT_PROVIDER]},
            bundle_uri="fs://connect-auth-agent/",
            bundle_sha256="a" * 64,
        )
        self.application.live_revision = revision
        self.application.save()

        base = f"/api/projects/{self.team.id}/agent_applications/{self.application.id}"
        self.url_list = f"{base}/identities/"
        self.url_connect = f"{base}/identities/dogs/connect/"
        self.url_disconnect = f"{base}/identities/dogs/"

    def _set_org_level(self, level: OrganizationMembership.Level) -> None:
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = level
        membership.save()

    # ── admin can use all three ──────────────────────────────────────────

    def test_admin_can_list(self) -> None:
        self._set_org_level(OrganizationMembership.Level.ADMIN)
        resp = self.client.get(self.url_list)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.json(), {"count": 0, "results": []})

    def test_admin_can_connect(self) -> None:
        self._set_org_level(OrganizationMembership.Level.ADMIN)
        resp = self.client.post(self.url_connect, {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        authorize_url = resp.json()["authorize_url"]
        self.assertTrue(authorize_url.startswith("https://dogs.example.com/oauth/authorize"))
        # The action actually minted a link-state row.
        self.assertTrue(
            AgentIdentityLinkState.all_teams.filter(application_id=self.application.id, provider="dogs").exists()
        )

    def test_admin_can_disconnect(self) -> None:
        self._set_org_level(OrganizationMembership.Level.ADMIN)
        AgentIdentityCredential.all_teams.create(
            team_id=self.team.id,
            application_id=self.application.id,
            agent_user_id=None,
            provider="dogs",
            encrypted_credentials="ciphertext",
            state="active",
        )
        resp = self.client.delete(self.url_disconnect)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.json(), {"provider": "dogs", "revoked": True})

    def test_admin_connect_unknown_provider_is_400(self) -> None:
        # AgentConnectError (config problem) surfaces as a 400, not a 500.
        self._set_org_level(OrganizationMembership.Level.ADMIN)
        resp = self.client.post(
            f"/api/projects/{self.team.id}/agent_applications/{self.application.id}/identities/ghost/connect/",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)

    # ── non-admin gets 404 on every action ───────────────────────────────

    def test_non_admin_cannot_list(self) -> None:
        self._set_org_level(OrganizationMembership.Level.MEMBER)
        resp = self.client.get(self.url_list)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_admin_cannot_connect(self) -> None:
        self._set_org_level(OrganizationMembership.Level.MEMBER)
        resp = self.client.post(self.url_connect, {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_admin_cannot_disconnect(self) -> None:
        self._set_org_level(OrganizationMembership.Level.MEMBER)
        resp = self.client.delete(self.url_disconnect)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
