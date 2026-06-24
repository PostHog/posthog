"""
Owner-initiated connect flow for agent-scoped identity providers (`binding: 'agent'`).

A `binding: 'agent'` identity provider is connected ONCE by an owner, not per
asker: the resulting OAuth credential is shared by every asker of the agent.
This module mints the authorize URL — writing the single-use PKCE link-state row
that the ingress `GET /link/<provider>/callback` later consumes — and lists /
revokes the app-scoped credential. The token exchange + storage happen node-side
in the ingress callback (`Oauth2AuthProvider.complete` → `putAgentScoped`).

The PKCE shape here MUST match the node `Oauth2AuthProvider.initiate`
(verifier = base64url(32 random bytes), challenge = base64url(sha256(verifier)),
S256) so the verifier we persist validates at the node token exchange.

Owner-gating is enforced by the caller (`AgentApplicationViewSet._require_team_admin`).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from django.conf import settings
from django.utils import timezone

from products.agent_platform.backend.models import AgentIdentityCredential, AgentIdentityLinkState

if TYPE_CHECKING:
    from products.agent_platform.backend.models import AgentApplication

_LINK_TTL = timedelta(minutes=10)


class AgentConnectError(Exception):
    """Connect can't proceed (unknown/non-agent provider, no live revision, missing client_id).

    Surfaced to the API as a 400 — it's an author/config problem, not a server error.
    """


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _ingress_base() -> str:
    # Matches posthog_identity_app.py so the registered redirect URI lines up.
    # No silent fallback: a self-hosted instance that forgot to set this would
    # otherwise register a redirect_uri pointing at PostHog Cloud's ingress —
    # routing the owner's OAuth completion (and the IdP's redirect trust) through
    # Cloud, where the link-state row doesn't exist. Fail loudly instead.
    base = settings.AGENT_INGRESS_PUBLIC_URL
    if not base:
        raise AgentConnectError(
            "AGENT_INGRESS_PUBLIC_URL is not configured — cannot build the OAuth callback URL for this instance."
        )
    return base.rstrip("/")


def _provider_effective_id(entry: dict[str, Any]) -> str | None:
    # Mirrors the zod default: a `posthog` entry defaults its id to "posthog".
    return entry.get("id") or ("posthog" if entry.get("kind") == "posthog" else None)


def _find_agent_provider(application: AgentApplication, provider_id: str) -> dict[str, Any]:
    """The `binding: 'agent'` identity-provider entry from the agent's LIVE spec.

    The live revision is what the ingress callback rebuilds the provider from, so
    the authorize params (client_id, scopes) must come from the same place.
    """
    revision = application.live_revision
    if revision is None:
        raise AgentConnectError("Promote the agent to a live revision before connecting an agent-level identity.")
    for entry in (revision.spec or {}).get("identity_providers") or []:
        if isinstance(entry, dict) and _provider_effective_id(entry) == provider_id:
            if entry.get("binding") != "agent":
                raise AgentConnectError(
                    f"Identity provider '{provider_id}' is per-principal; each user connects it themselves."
                )
            return entry
    raise AgentConnectError(f"No agent-level identity provider '{provider_id}' on this agent.")


def mint_authorize_url(application: AgentApplication, provider_id: str) -> str:
    """Create a single-use link-state row and return the IdP authorize URL.

    The owner opens this URL, authorizes, and the ingress callback stores the
    shared credential app-scoped. Caller must have already authorized the owner.
    """
    entry = _find_agent_provider(application, provider_id)
    kind = entry.get("kind")
    scopes = [str(s) for s in (entry.get("scopes") or [])]

    if kind == "posthog":
        authorize_url = f"{settings.SITE_URL.rstrip('/')}/oauth/authorize/"
        client_id = entry.get("client_id")
        if not client_id:
            raise AgentConnectError("This PostHog identity provider has no client_id yet — promote the agent first.")
    elif kind == "oauth2":
        oauth_authorize_url = entry.get("authorize_url")
        client_id = entry.get("client_id")
        if not oauth_authorize_url or not client_id:
            raise AgentConnectError("OAuth2 identity provider is missing authorize_url or client_id.")
        # Narrowed to non-None above; assign through a temp so it unifies with the
        # `str` the posthog branch assigns (an Any|None straight to `authorize_url`
        # trips mypy's cross-branch type inference).
        authorize_url = oauth_authorize_url
    else:
        raise AgentConnectError(f"Unsupported identity provider kind '{kind}'.")

    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    redirect_uri = f"{_ingress_base()}/link/{provider_id}/callback"

    # Idempotency: a re-clicked connect (or a retried POST) shouldn't leave a trail
    # of live link-state rows. Retire any prior unconsumed, unexpired agent-scoped
    # rows for this provider before minting a fresh one. (The janitor sweep also
    # reaps expired/used rows; this keeps the live set to one.)
    AgentIdentityLinkState.all_teams.filter(
        application_id=application.id,
        provider=provider_id,
        agent_user_id__isnull=True,
        used_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).update(used_at=timezone.now())

    link = AgentIdentityLinkState.all_teams.create(
        team_id=application.team_id,
        application_id=application.id,
        agent_user_id=None,  # agent-scoped: no asking principal
        provider=provider_id,
        scopes=scopes,
        code_verifier=verifier,
        redirect_uri=redirect_uri,
        expires_at=timezone.now() + _LINK_TTL,
    )

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": str(link.id),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if scopes:
        params["scope"] = " ".join(scopes)
    return f"{authorize_url}?{urlencode(params)}"


def list_connections(application: AgentApplication) -> list[dict[str, Any]]:
    """Agent-level (shared) identity connections — metadata only, never credential material."""
    rows = AgentIdentityCredential.all_teams.filter(application_id=application.id, agent_user_id__isnull=True).order_by(
        "provider"
    )
    return [
        {
            "provider": r.provider,
            "state": r.state,
            "scopes": list(r.scopes or []),
            "subject": r.subject,
            "access_expires_at": r.access_expires_at.isoformat() if r.access_expires_at else None,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
            "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
        }
        for r in rows
    ]


def revoke_connection(application: AgentApplication, provider_id: str) -> bool:
    """Revoke the agent-level credential for a provider (row kept for audit). True if one was active.

    Takes effect on the next credential resolution — each tool/MCP call re-reads the
    row filtered to state='active', so the next resolve returns "not connected". An
    MCP connection already opened with the bearer keeps it until that connection ends.
    """
    updated = AgentIdentityCredential.all_teams.filter(
        application_id=application.id,
        provider=provider_id,
        agent_user_id__isnull=True,
        state="active",
    ).update(state="revoked", revoked_at=timezone.now(), updated_at=timezone.now())
    return updated > 0
