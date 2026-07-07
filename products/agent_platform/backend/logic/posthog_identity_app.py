"""
Managed PostHog identity provider provisioning.

When an agent revision declares an identity provider of `{kind: "posthog"}`, the
runtime needs a real OAuthApplication to run the link flow against. On promote we
ensure that app exists (a NORMAL, user-consented app — deliberately not
first-party, so linking shows PostHog's standard "allow this app to act as you"
consent) and inject its `client_id` into the frozen spec, where the runner reads
it. Idempotent: keyed on (organization, name); safe to call on every promote.

Mirrors the org-scoped, select_for_update provisioning in
posthog/api/oauth/toolbar_service.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.db import transaction

import structlog

from posthog.models import Organization, Team, User
from posthog.models.oauth import OAuthApplication

if TYPE_CHECKING:
    from products.agent_platform.backend.models import AgentApplication, AgentRevision

logger = structlog.get_logger(__name__)

# Fallback when AGENT_INGRESS_PUBLIC_URL is unset — matches the runner's
# linkRedirectBaseUrl default so the registered redirect URI lines up.
_DEFAULT_INGRESS_BASE = "https://agents.posthog.com"


def _ingress_base() -> str:
    return (settings.AGENT_INGRESS_PUBLIC_URL or _DEFAULT_INGRESS_BASE).rstrip("/")


def _ensure_oauth_app(
    *, organization: Organization, user: User | None, name: str, redirect_uri: str, scopes: list[str]
) -> OAuthApplication:
    """Get-or-create the org's identity app for this agent. select_for_update on
    the org row serializes first-time creation (no DB unique constraint for this
    shape, same as the toolbar app)."""
    with transaction.atomic():
        Organization.objects.select_for_update().get(pk=organization.pk)

        existing = OAuthApplication.objects.filter(
            organization=organization,
            name=name,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
        ).first()
        if existing:
            changed: list[str] = []
            if existing.redirect_uris != redirect_uri:
                existing.redirect_uris = redirect_uri
                changed.append("redirect_uris")
            if list(existing.scopes or []) != list(scopes):
                existing.scopes = scopes
                changed.append("scopes")
            if changed:
                existing.save(update_fields=changed)
            return existing

        return OAuthApplication.objects.create(
            name=name,
            user=user,
            organization=organization,
            client_type=OAuthApplication.CLIENT_PUBLIC,  # PKCE, no client secret
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris=redirect_uri,
            algorithm="RS256",
            scopes=scopes,
            # is_first_party stays False → the user sees the consent screen.
        )


def provision_posthog_identity_apps(
    *, application: AgentApplication, revision: AgentRevision, acting_user: User | None
) -> bool:
    """Ensure an OAuthApplication for every `{kind: posthog}` identity provider in
    the revision spec and inject its `client_id` into the spec. Returns True if the
    spec was mutated (caller must persist `revision.spec`)."""
    spec = revision.spec or {}
    providers = spec.get("identity_providers") or []
    posthog_entries = [p for p in providers if isinstance(p, dict) and p.get("kind") == "posthog"]
    if not posthog_entries:
        return False

    organization = Team.objects.get(pk=application.team_id).organization
    base = _ingress_base()

    mutated = False
    for entry in posthog_entries:
        provider_id = entry.get("id") or "posthog"
        redirect_uri = f"{base}/link/{provider_id}/callback"
        scopes = list(entry.get("scopes") or [])
        # Stable, readable, org-unique per (agent, provider).
        name = f"Agent identity · {application.slug} · {provider_id}"

        app = _ensure_oauth_app(
            organization=organization,
            user=acting_user,
            name=name,
            redirect_uri=redirect_uri,
            scopes=scopes,
        )
        if entry.get("client_id") != app.client_id:
            entry["client_id"] = app.client_id
            mutated = True

    if mutated:
        logger.info(
            "agent_posthog_identity_app_provisioned",
            application_id=str(application.id),
            revision_id=str(revision.id),
            providers=[e.get("id") or "posthog" for e in posthog_entries],
        )
    return mutated
