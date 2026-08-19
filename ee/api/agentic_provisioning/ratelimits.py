"""Partner rate limits for the agentic provisioning API.

Every partner-scoped limit is a token bucket (:mod:`posthog.token_bucket`)
whose size is declared on the endpoint handler with :func:`rate_limited` and
scaled by the partner's derived tier
(:class:`~posthog.models.oauth_provisioning.PartnerTier`): stronger client
authentication and attestation each raise the budget, with no stored state and
no admin involvement. An explicit per-partner override in the provisioning
config outranks the computed value.

Charging happens two ways, mirroring where the partner becomes known:

- ``charge="auto"``: the base view charges in ``check_throttles`` from the
  partner on ``request.auth``. Runs after the per-IP throttles, so a request
  those refuse spends no partner quota.
- ``charge="manual"``: the handler calls ``self.charge_rate_limit(...)`` once
  it has resolved its partner (the token endpoint decodes a grant first,
  account_requests must clear the capability check before spending quota), or
  a flow outside any view (the bundled account-request wizard block) calls
  :func:`charge_partner_by_name`.

A charge is refunded in ``handle_exception`` when the request provably did no
work (the error code is in the declaration's ``refund_on``), so a partner
debugging a 400 does not spend its budget on rejections.

The buckets are best-effort: Redis eviction or an outage hands a caller a
fresh budget, and charging fails open. ``account_requests`` therefore also
carries a durable ceiling, a Postgres count of the accounts the partner
actually created in the last day, which stays correct when Redis cannot.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import ClassVar, Literal

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

import structlog
from prometheus_client import Counter, Histogram
from rest_framework.request import Request

from posthog.dataclasses import frozen
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.oauth_provisioning import PartnerTier
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig
from posthog.token_bucket import BucketDecision, BucketUnavailable, Budget, consume, refund

from ee.api.agentic_provisioning.analytics import capture_provisioning_event
from ee.api.agentic_provisioning.exceptions import Envelope, ProvisioningError

logger = structlog.get_logger(__name__)

BUCKET_KEY_PREFIX = "provisioning_bucket:"

RATE_LIMITED_MESSAGE = "Rate limit exceeded for this partner. Try again later."
TIER_BLOCKED_MESSAGE = (
    "This endpoint is not available for this partner's tier. "
    "Publish a JWKS document or verify your organization to raise your tier."
)

# One PUBLIC-tier budget fits most endpoints; only endpoints where it is wrong
# declare their own. Scaling: PUBLIC x1, PUBLIC_ATTESTED x2, JWKS x5, JWKS_ATTESTED x10.
DEFAULT_BUDGET = Budget(burst=30, per_hour=120)
TIER_MULTIPLIERS: dict[PartnerTier, int] = {
    PartnerTier.PUBLIC: 1,
    PartnerTier.PUBLIC_ATTESTED: 2,
    PartnerTier.JWKS: 5,
    PartnerTier.JWKS_ATTESTED: 10,
}
# A tier multiplier of BLOCKED means the tier may not use the endpoint at all.
# An explicit per-partner override outranks it.
BLOCKED = 0
# Multipliers for budgets that must not scale with tier (polling caps).
FLAT_MULTIPLIERS: dict[PartnerTier, int] = dict.fromkeys(TIER_MULTIPLIERS, 1)

# Error codes whose requests provably did no work: pure rejections raised
# before any side effect or outbound call. Any invalid_* code counts as no-work
# too (see _did_no_work), so validation codes need no entry here. Codes like
# github_unavailable are deliberately absent because the outbound call already
# happened.
DID_NO_WORK_CODES: frozenset[str] = frozenset(
    {
        "forbidden",
        "unauthorized",
        "not_found",
        "no_team",
        "team_not_found",
        "grant_not_found",
        "deep_links_not_enabled",
        "wizard_unavailable",
    }
)

# The endpoints whose per-partner override fields exist on ProvisioningRateLimits
# today. Endpoints outside this set are tier-derived only until the override
# storage becomes a per-endpoint dict.
LEGACY_OVERRIDE_ENDPOINTS: frozenset[str] = frozenset(
    {"account_requests", "token_exchanges", "resource_creates", "github_grants", "wizard_runs"}
)

DECISIONS_COUNTER = Counter(
    "provisioning_rate_limit_decisions_total",
    "Partner rate limit decisions on the agentic provisioning API.",
    labelnames=["endpoint", "tier", "outcome"],
)
HEADROOM_HISTOGRAM = Histogram(
    "provisioning_rate_limit_headroom_ratio",
    "Remaining/limit ratio at decision time, for spotting partners near their budget.",
    labelnames=["endpoint", "tier"],
    buckets=(0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0),
)
BACKEND_ERRORS_COUNTER = Counter(
    "provisioning_rate_limit_backend_errors_total",
    "Rate limit decisions Redis could not answer, by fallback mode.",
    labelnames=["endpoint", "mode"],
)
ACCOUNT_CEILING_COUNTER = Counter(
    "provisioning_account_ceiling_hits_total",
    "Account requests rejected by the durable daily account-creation ceiling.",
    labelnames=["tier"],
)


@frozen
class BudgetDeclaration:
    endpoint: str
    budget: Budget
    multipliers: Mapping[PartnerTier, int]
    charge: Literal["auto", "manual"]
    refund_on: frozenset[str]
    durable_ceiling: Callable[[OAuthApplication, Budget], None] | None
    key: Callable[[Request, object], str] | None
    # Overrides the view's error envelope on the 429 (the token endpoint keeps
    # the typed envelope, its historical wire shape).
    envelope: Envelope | None


@frozen(frozen=False)
class RateLimitLedger:
    """One charge against a bucket, kept on the request for refunds and headers."""

    declaration: BudgetDeclaration
    bucket_key: str
    budget: Budget
    decision: BucketDecision
    tier: PartnerTier
    refunded: bool = False

    LEDGERS_ATTR: ClassVar[str] = "_provisioning_ledgers"


_REGISTRY: dict[str, BudgetDeclaration] = {}


def rate_limited(
    endpoint: str,
    *,
    budget: Budget = DEFAULT_BUDGET,
    multipliers: Mapping[PartnerTier, int] | None = None,
    charge: Literal["auto", "manual"] = "auto",
    refund_on: frozenset[str] = DID_NO_WORK_CODES,
    durable_ceiling: Callable[[OAuthApplication, Budget], None] | None = None,
    key: Callable[[Request, object], str] | None = None,
    envelope: Envelope | None = None,
) -> Callable:
    """Declare an endpoint's rate limit budget on its handler.

    Pure metadata, like DRF's own ``@throttle_classes``: nothing is wrapped, the
    base view reads the declaration from the handler. ``multipliers`` merges over
    :data:`TIER_MULTIPLIERS`, so an endpoint states only the cells where the
    default grid is wrong. Stacking two declarations on one handler is allowed
    (the token endpoint charges different buckets per grant type); a manual
    handler with several then names the endpoint when it charges.
    """
    declaration = BudgetDeclaration(
        endpoint=endpoint,
        budget=budget,
        multipliers={**TIER_MULTIPLIERS, **(multipliers or {})},
        charge=charge,
        refund_on=refund_on,
        durable_ceiling=durable_ceiling,
        key=key,
        envelope=envelope,
    )

    existing = _REGISTRY.get(endpoint)
    if existing is not None and existing != declaration:
        raise ImproperlyConfigured(
            f"Conflicting rate limit declarations for endpoint {endpoint!r}. "
            "One endpoint name means one budget; declare it once and share it."
        )
    _REGISTRY[endpoint] = declaration

    def decorate(handler: Callable) -> Callable:
        budgets = dict(getattr(handler, "_provisioning_budgets", {}))
        budgets[endpoint] = declaration
        handler._provisioning_budgets = budgets  # type: ignore[attr-defined]
        return handler

    return decorate


def registered_budgets() -> Mapping[str, BudgetDeclaration]:
    """Every declared endpoint budget, for introspection surfaces."""
    return dict(_REGISTRY)


def partner_for_rate_limiting(request: Request) -> OAuthApplication | None:
    """The app to charge, from either bearer or client authentication.

    Keyed on carrying provisioning config rather than is_provisioning_partner, so
    disabling a partner does not also un-throttle its outstanding tokens. Plain
    OAuth apps whose tokens reach these endpoints carry no partner quota.
    """
    auth = request.auth
    if isinstance(auth, OAuthAccessToken):
        app = auth.application
    elif isinstance(auth, OAuthApplication):
        app = auth
    else:
        return None
    if app is None or not app.carries_provisioning_config:
        return None
    return app


def _legacy_override(partner: OAuthApplication, endpoint: str) -> int | None:
    if endpoint not in LEGACY_OVERRIDE_ENDPOINTS:
        return None
    return getattr(partner.provisioning.rate_limits, endpoint, None)


def resolve_budget(declaration: BudgetDeclaration, partner: OAuthApplication) -> Budget | None:
    """The bucket to charge for this partner, or None when it is unlimited.

    Raises the tier-blocked error when the tier multiplier is BLOCKED and no
    override exists; an admin override outranks BLOCKED, so a specific partner
    can be granted an endpoint without moving its whole tier.
    """
    tier = partner.partner_tier
    multiplier = declaration.multipliers[tier]
    override = _legacy_override(partner, declaration.endpoint)

    if override is not None:
        if override <= 0:
            return None
        # The override replaces the hourly rate; burst keeps the endpoint's
        # declared burst-to-rate proportion, independent of tier, so an
        # override means the same thing whatever tier the partner sits on.
        burst = max(1, math.ceil(declaration.budget.burst * override / declaration.budget.per_hour))
        return Budget(burst=burst, per_hour=override)

    if multiplier == BLOCKED:
        DECISIONS_COUNTER.labels(endpoint=declaration.endpoint, tier=tier, outcome="tier_blocked").inc()
        capture_provisioning_event("rate_limited", "tier_blocked", partner=partner, endpoint=declaration.endpoint)
        raise ProvisioningError("forbidden", TIER_BLOCKED_MESSAGE, status=403, envelope=declaration.envelope)

    return Budget(burst=declaration.budget.burst * multiplier, per_hour=declaration.budget.per_hour * multiplier)


def _bucket_key(endpoint: str, partner: OAuthApplication, key_suffix: str = "") -> str:
    key = f"{BUCKET_KEY_PREFIX}{endpoint}:{partner.id}"
    return f"{key}:{key_suffix}" if key_suffix else key


def charge_partner(
    declaration: BudgetDeclaration,
    partner: OAuthApplication,
    *,
    request: Request | None = None,
    key_suffix: str = "",
    resource_id: str = "",
) -> None:
    """Charge one request against the partner's bucket for this endpoint.

    Raises the wire-contract ``rate_limited`` error when over budget. When a
    request is passed, the charge lands on its ledger so ``handle_exception``
    can refund it and ``finalize_response`` can emit RateLimit-* headers.
    """
    tier = partner.partner_tier
    budget = resolve_budget(declaration, partner)
    if budget is None:
        return

    bucket_key = _bucket_key(declaration.endpoint, partner, key_suffix)

    decision = consume(bucket_key, budget)
    if isinstance(decision, BucketUnavailable):
        # Fail open: an unreachable Redis must not take the API down. The
        # durable ceiling below still bounds the one endpoint where a free
        # window matters.
        mode = "fell_through_to_db" if declaration.durable_ceiling else "failed_open"
        BACKEND_ERRORS_COUNTER.labels(endpoint=declaration.endpoint, mode=mode).inc()
        if declaration.durable_ceiling is not None:
            declaration.durable_ceiling(partner, budget)
        return

    HEADROOM_HISTOGRAM.labels(endpoint=declaration.endpoint, tier=tier).observe(
        decision.remaining / decision.limit if decision.limit else 0.0
    )

    if request is not None:
        ledgers = getattr(request, RateLimitLedger.LEDGERS_ATTR, None)
        if ledgers is None:
            ledgers = []
            setattr(request, RateLimitLedger.LEDGERS_ATTR, ledgers)
        ledgers.append(
            RateLimitLedger(declaration=declaration, bucket_key=bucket_key, budget=budget, decision=decision, tier=tier)
        )

    if not decision.allowed:
        DECISIONS_COUNTER.labels(endpoint=declaration.endpoint, tier=tier, outcome="throttled").inc()
        capture_provisioning_event(
            "rate_limited",
            "rate_limited",
            partner=partner,
            endpoint=declaration.endpoint,
            limit=budget.per_hour,
            retry_after=decision.retry_after,
        )
        raise ProvisioningError(
            "rate_limited",
            RATE_LIMITED_MESSAGE,
            status=429,
            envelope=declaration.envelope,
            resource_id=resource_id,
            retry_after=decision.retry_after,
        )

    DECISIONS_COUNTER.labels(endpoint=declaration.endpoint, tier=tier, outcome="allowed").inc()

    if declaration.durable_ceiling is not None:
        declaration.durable_ceiling(partner, budget)


def charge_partner_by_name(
    endpoint: str, partner: OAuthApplication, *, request: Request | None = None, resource_id: str = ""
) -> None:
    """Charge by registry name, for flows that run outside any view dispatch
    (the bundled account-request wizard block)."""
    declaration = _REGISTRY.get(endpoint)
    if declaration is None:
        # Declarations register when the view modules import. Web processes load
        # them through the URLconf; anything else (a test importing accounts.py
        # directly) gets them here. Function-local to break the views->ratelimits
        # import cycle.
        from ee.api.agentic_provisioning import views  # noqa: F401, PLC0415

        declaration = _REGISTRY.get(endpoint)
    if declaration is None:
        raise ImproperlyConfigured(f"No rate limit declared for endpoint {endpoint!r}")
    charge_partner(declaration, partner, request=request, resource_id=resource_id)


def _did_no_work(error_code: str, refund_on: frozenset[str]) -> bool:
    # invalid_* is the convention every validation rejection follows, including
    # per-endpoint serializer codes (invalid_label_prefix, invalid_path, ...), so
    # the prefix refunds them without enumerating each one.
    return error_code in refund_on or error_code.startswith("invalid_")


def refund_no_work(request: Request, error_code: str) -> None:
    """Give charges back when the request's failure proves it did no work."""
    for ledger in getattr(request, RateLimitLedger.LEDGERS_ATTR, []):
        if ledger.refunded or not _did_no_work(error_code, ledger.declaration.refund_on):
            continue
        refund(ledger.bucket_key, ledger.budget)
        ledger.refunded = True
        DECISIONS_COUNTER.labels(endpoint=ledger.declaration.endpoint, tier=ledger.tier, outcome="refunded").inc()


def apply_rate_limit_headers(request: Request, response) -> None:
    """RateLimit-Limit/Remaining/Reset on every response that charged a bucket,
    so a partner can pace itself instead of discovering the limit through 429s."""
    ledgers = getattr(request, RateLimitLedger.LEDGERS_ATTR, None)
    if not ledgers:
        return
    ledger = ledgers[-1]
    remaining = ledger.decision.remaining + (1 if ledger.refunded else 0)
    response["RateLimit-Limit"] = str(ledger.decision.limit)
    response["RateLimit-Remaining"] = str(min(remaining, ledger.decision.limit))
    response["RateLimit-Reset"] = str(ledger.decision.reset)


def account_creation_daily_ceiling(partner: OAuthApplication, budget: Budget) -> None:
    """Durable backstop on account creation: the Redis bucket forgets on
    eviction or failover, this Postgres count of accounts the partner actually
    created in the last day does not. Sized to the bucket's own daily
    throughput, so it only bites when the bucket lost state."""
    # Not serialized: locking the partner row would put every account request behind
    # one writer to hold a cap that is already coarse (a day of bucket throughput), and
    # overshoot is bounded by how many requests one partner has in flight at once.
    cap = budget.per_hour * 24 + budget.burst
    since = timezone.now() - timedelta(days=1)
    created = TeamProvisioningConfig.objects.filter(application=partner, created_at__gte=since).count()
    if created < cap:
        return
    tier = partner.partner_tier
    ACCOUNT_CEILING_COUNTER.labels(tier=tier).inc()
    capture_provisioning_event(
        "rate_limited", "account_ceiling", partner=partner, endpoint="account_requests", limit=cap, created=created
    )
    raise ProvisioningError(
        "rate_limited",
        "Daily account creation limit reached for this partner. Try again later.",
        status=429,
        retry_after=3600,
    )
