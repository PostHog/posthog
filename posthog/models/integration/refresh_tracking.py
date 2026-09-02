"""OAuth refresh bookkeeping shared across every OAuth-backed integration kind."""

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import model


import structlog
from prometheus_client import Counter

from . import common

logger = structlog.get_logger(__name__)


oauth_refresh_counter = Counter(
    "integration_oauth_refresh",
    "Number of times an oauth refresh has been attempted",
    labelnames=["kind", "result", "reason", "attempt"],
)

# Terminal rows are skipped by the sweep and stop emitting failure metrics, so a gradual fleet
# die-off would otherwise be invisible. Incremented once per row at the transition; a rising
# rate means connections are permanently breaking (e.g. a provider mass-revoking grants).
oauth_refresh_terminal_counter = Counter(
    "integration_oauth_refresh_went_terminal",
    "OAuth integrations whose refresh went terminal (unbroken invalid_grant streak)",
    labelnames=["kind"],
)

# Consecutive-failure backoff for the every-minute refresh sweep (posthog/tasks/integrations.py).
# Without it, permanently dead integrations (revoked grants, deleted consumers) are retried every
# minute forever, hammering providers and drowning the failure metric in a noise floor that
# masks real fleet-wide breakage.
REFRESH_BACKOFF_BASE_SECONDS = 120

REFRESH_BACKOFF_MAX_SECONDS = 3600

REFRESH_TERMINAL_FAILURE_COUNT = 5

# `config` key flagging a grant that only the legacy fallback credentials can refresh.
CONFIG_LEGACY_OAUTH_CLIENT = "oauth_uses_legacy_client"

# Values for the counter's `reason` label, bucketed from the OAuth error response.
REFRESH_FAILURE_REASON_INVALID_GRANT = "invalid_grant"

REFRESH_FAILURE_REASON_INVALID_CLIENT = "invalid_client"

REFRESH_FAILURE_REASON_HTTP_5XX = "http_5xx"

REFRESH_FAILURE_REASON_NETWORK = "network"

REFRESH_FAILURE_REASON_RATE_LIMITED = "rate_limited"

REFRESH_FAILURE_REASON_OTHER = "other"

# Not a provider response: the stored refresh token itself can't be decrypted, so no request was
# made. Terminal on the first occurrence, since no later attempt can make the secret readable.
REFRESH_FAILURE_REASON_UNREADABLE_SECRET = "unreadable_secret"


def oauth_refresh_failure_reason(status_code: int, body: dict, kind: str | None = None) -> str:
    error = body.get("error")
    if error == REFRESH_FAILURE_REASON_INVALID_GRANT:
        return REFRESH_FAILURE_REASON_INVALID_GRANT
    if error == REFRESH_FAILURE_REASON_INVALID_CLIENT:
        return REFRESH_FAILURE_REASON_INVALID_CLIENT
    # Reddit reports a dead grant as `{"message": "Bad Request", "error": 400}` with no OAuth
    # error code. Our refresh request shape is fixed and succeeds fleet-wide, so a 400 on this
    # endpoint means the grant, not the request - match that exact shape for reddit only.
    if kind == "reddit-ads" and status_code == 400 and error == 400:
        return REFRESH_FAILURE_REASON_INVALID_GRANT
    # HubSpot reports a grant whose portal (hub) was deleted or disconnected as
    # `{"status": "BAD_HUB", "error": "access_denied", ...}` - no `invalid_grant` code, so
    # without this mapping the row is retried forever instead of going terminal. Its
    # `BAD_REFRESH_TOKEN` responses do carry `"error": "invalid_grant"` and need no special case.
    if kind == "hubspot" and status_code < 500 and body.get("status") == "BAD_HUB":
        return REFRESH_FAILURE_REASON_INVALID_GRANT
    # Meta Graph nests its error as an object (`{"error": {"code": 190, ...}}`) and never
    # sends the `invalid_grant` string. Code 190 means the access token is dead (password
    # change, checkpoint, expiry, revocation). Without this mapping, a revoked Meta token
    # classifies as `other`. Meta rate limits use codes 4, 17, and 32, which do not match.
    if kind in ("meta-ads", "instagram") and status_code < 500 and isinstance(error, dict) and error.get("code") == 190:
        return REFRESH_FAILURE_REASON_INVALID_GRANT
    # Transient throttling, not a credential problem: the backoff cap synchronises failed
    # integrations into retry herds that can trip a provider's per-second limit and take
    # healthy refreshes in the same second down with them.
    if status_code == 429:
        return REFRESH_FAILURE_REASON_RATE_LIMITED
    if status_code >= 500:
        return REFRESH_FAILURE_REASON_HTTP_5XX
    return REFRESH_FAILURE_REASON_OTHER


def record_refresh_failure(integration: "model.Integration", *, reason: str = REFRESH_FAILURE_REASON_OTHER) -> str:
    """Track a consecutive refresh failure on the integration's config; caller saves.

    Schedules the next attempt with capped exponential backoff. `invalid_grant` means the grant
    itself is dead and only a customer re-auth can fix it, so after an unbroken streak of them the
    integration goes terminal and the sweep stops retrying entirely. The streak is tracked
    separately from the total failure count and resets on any other reason, so one transient
    invalid_grant amid e.g. a 5xx outage can't brick the integration. `unreadable_secret` goes
    terminal on the first occurrence - we never even reached the provider, and retrying can't make
    an undecryptable token readable. Other reasons (invalid_client, 5xx, network, rate_limited)
    never go terminal - a platform-side credential fix must let the fleet self-recover.

    Returns "first"/"retry" for the metric's `attempt` label - a spike in first failures means
    connections are newly breaking, regardless of retry noise.
    """
    count = int(integration.config.get("refresh_failure_count") or 0)
    attempt = "first" if count == 0 else "retry"
    count += 1
    integration.config["refresh_failure_count"] = count
    integration.config["refresh_next_attempt_at"] = int(time.time()) + min(
        REFRESH_BACKOFF_BASE_SECONDS * 2 ** (count - 1), REFRESH_BACKOFF_MAX_SECONDS
    )
    if reason == REFRESH_FAILURE_REASON_UNREADABLE_SECRET:
        integration.config.pop("refresh_invalid_grant_count", None)
        if not integration.config.get("refresh_terminal"):
            integration.config["refresh_terminal"] = True
            oauth_refresh_terminal_counter.labels(kind=integration.kind).inc()
    elif reason == REFRESH_FAILURE_REASON_INVALID_GRANT:
        grant_streak = int(integration.config.get("refresh_invalid_grant_count") or 0) + 1
        integration.config["refresh_invalid_grant_count"] = grant_streak
        # Guarded so on-demand refreshes (which bypass the backoff) can't re-count a dead row
        if grant_streak >= REFRESH_TERMINAL_FAILURE_COUNT and not integration.config.get("refresh_terminal"):
            integration.config["refresh_terminal"] = True
            oauth_refresh_terminal_counter.labels(kind=integration.kind).inc()
    else:
        integration.config.pop("refresh_invalid_grant_count", None)
    return attempt


def record_refresh_success(integration: "model.Integration") -> None:
    for key in ("refresh_failure_count", "refresh_invalid_grant_count", "refresh_next_attempt_at", "refresh_terminal"):
        integration.config.pop(key, None)


def record_oauth_client_used(integration: "model.Integration", *, used_fallback: bool) -> None:
    """Track whether the grant still depends on the legacy (fallback) OAuth credentials.

    A refresh token minted by a since-migrated app can only be refreshed by that app's
    credentials, so a successful fallback refresh identifies exactly the connections that break
    when the legacy app is retired. The flag rides on `config`, which the API exposes, so the
    product can tell those teams to reconnect. Reconnecting mints a grant on the primary
    credentials and replaces `config` wholesale, which clears the flag.
    """
    if used_fallback:
        integration.config[CONFIG_LEGACY_OAUTH_CLIENT] = True
    else:
        integration.config.pop(CONFIG_LEGACY_OAUTH_CLIENT, None)


def issuing_oauth_client_ids(integration: "model.Integration") -> list[str]:
    """The OAuth client ids the connection was established with. Empty when that can't be read.

    OIDC puts the client id in the id_token's `aud` claim, and we keep the id_token from the
    authorization exchange - refreshes only overwrite the access and refresh tokens. So this reads
    the app the customer actually connected through, which is knowable for connections that already
    exist, without waiting for a refresh to reveal it.

    `aud` is a string or a list of strings per RFC 7519, so both shapes are normalized here.
    Callers should test membership rather than assume a single value: treating a list-shaped
    audience as unreadable would silently drop those connections from the reconnect campaign.
    """
    id_token = integration.sensitive_config.get("id_token")
    if not id_token:
        return []
    try:
        claims = common._decode_jwt_payload(id_token) or {}
    except Exception:
        logger.warning("Failed to decode id_token", integration_id=integration.id, kind=integration.kind)
        return []
    audience = claims.get("aud")
    if isinstance(audience, str):
        return [audience]
    if isinstance(audience, list):
        return [entry for entry in audience if isinstance(entry, str)]
    return []


def refresh_backoff_active(integration: "model.Integration") -> bool:
    """Whether the refresh sweep should skip this integration. Reconnecting resets the state
    (the OAuth callback replaces `config` wholesale), and on-demand API refreshes bypass this."""
    if integration.config.get("refresh_terminal"):
        return True
    next_attempt_at = integration.config.get("refresh_next_attempt_at")
    return bool(next_attempt_at) and time.time() < next_attempt_at
