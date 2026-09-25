from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Any, Concatenate, ParamSpec, TypeVar
from uuid import UUID

from django.core.cache import cache
from django.http import HttpRequest

import structlog
from loginas.utils import is_impersonated_session

from posthog.cloud_utils import get_cached_instance_license
from posthog.dataclasses import frozen
from posthog.helpers.two_factor_session import missing_two_factor_step
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain

if TYPE_CHECKING:
    from posthog.models.user import User
    from posthog.user_permissions import UserPermissions

logger = structlog.get_logger(__name__)

# Bounds how long a billing change made outside PostHog (for example in the Stripe portal)
# can take to reach the server-rendered app context when no invalidation reaches us.
BILLING_RESPONSE_CACHE_TTL_SECONDS = 5 * 60

# `include_forecasting=false` is the only variant the app requests. Other values are not cached,
# so invalidation only has to know these two.
_FORECASTING_VARIANTS: dict[str | None, str] = {None: "default", "false": "no_forecasting"}

P = ParamSpec("P")
R = TypeVar("R")
M = TypeVar("M")


def _cache_key(organization_id: UUID | str, membership_level: int, variant: str) -> str:
    return f"billing_response:{organization_id}:{membership_level}:{variant}"


def _all_cache_keys(organization_id: UUID | str) -> list[str]:
    return [
        _cache_key(organization_id, level, variant)
        for level in OrganizationMembership.Level
        for variant in _FORECASTING_VARIANTS.values()
    ]


def cache_billing_response(
    organization_id: UUID | str,
    membership_level: int,
    include_forecasting: str | None,
    response: dict[str, Any],
) -> None:
    # The billing service receives the caller's organization role in its token, so an entry is
    # keyed on that role. A response built for an owner is then never served to a member.
    variant = _FORECASTING_VARIANTS.get(include_forecasting)
    if variant is None:
        return
    try:
        cache.set(
            _cache_key(organization_id, membership_level, variant),
            response,
            timeout=BILLING_RESPONSE_CACHE_TTL_SECONDS,
        )
    except Exception:
        logger.warning("billing_response_cache_write_failed", exc_info=True)


def get_cached_billing_response(organization_id: UUID | str, membership_level: int) -> dict[str, Any] | None:
    keys = [_cache_key(organization_id, membership_level, variant) for variant in _FORECASTING_VARIANTS.values()]
    try:
        cached = cache.get_many(keys)
    except Exception:
        logger.warning("billing_response_cache_read_failed", exc_info=True)
        return None
    for key in keys:
        value = cached.get(key)
        if isinstance(value, dict):
            return value
    return None


def invalidate_billing_cache(organization_id: UUID | str) -> None:
    try:
        cache.delete_many(_all_cache_keys(organization_id))
    except Exception:
        logger.warning("billing_response_cache_invalidate_failed", exc_info=True)


def invalidates_billing_cache(
    method: Callable[Concatenate[M, Organization, P], R],
) -> Callable[Concatenate[M, Organization, P], R]:
    """Clear the organization's cached billing response after a billing service call that can change it.

    The cache is cleared in `finally` because a call that raises can still have changed state in billing.
    """

    @wraps(method)
    def wrapper(self: M, organization: Organization, *args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return method(self, organization, *args, **kwargs)
        finally:
            invalidate_billing_cache(organization.id)

    return wrapper


def has_active_v1_billing(organization: Organization) -> bool:
    # `Organization.billing` is the legacy V1 billing relation, and getattr tolerates a deployment that lacks it.
    billing = getattr(organization, "billing", None)
    return bool(billing and billing.stripe_subscription_id)


@frozen
class BillingSummaryTrial:
    type: str | None
    status: str | None
    target: str | None
    expires_at: str | None


@frozen
class BillingSummaryAccountOwner:
    name: str | None
    email: str | None


@frozen
class BillingSummaryProduct:
    type: str
    name: str
    usage_key: str | None
    percentage_usage: float
    subscribed: bool | None


@frozen
class BillingSummary:
    """The fields of the billing response that every page reads: billing alerts and the account owner.

    The frontend mirrors this shape as `BillingSummary` in `frontend/src/types.ts`. The full response is
    too large to put into every server-rendered page.
    """

    deactivated: bool
    current_period_end: str | None
    trial: BillingSummaryTrial | None
    account_owner: BillingSummaryAccountOwner | None
    products: tuple[BillingSummaryProduct, ...]


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def summarize_billing_response(response: dict[str, Any]) -> BillingSummary:
    trial = response.get("trial")
    account_owner = response.get("account_owner")
    products = response.get("products")
    return BillingSummary(
        deactivated=bool(response.get("deactivated")),
        current_period_end=_optional_str(_as_dict(response.get("billing_period")).get("current_period_end")),
        trial=BillingSummaryTrial(
            type=_optional_str(trial.get("type")),
            status=_optional_str(trial.get("status")),
            target=_optional_str(trial.get("target")),
            expires_at=_optional_str(trial.get("expires_at")),
        )
        if isinstance(trial, dict)
        else None,
        account_owner=BillingSummaryAccountOwner(
            name=_optional_str(account_owner.get("name")),
            email=_optional_str(account_owner.get("email")),
        )
        if isinstance(account_owner, dict)
        else None,
        products=tuple(
            BillingSummaryProduct(
                type=product["type"],
                name=_optional_str(product.get("name")) or product["type"],
                usage_key=_optional_str(product.get("usage_key")),
                percentage_usage=float(product.get("percentage_usage") or 0),
                subscribed=product.get("subscribed") if isinstance(product.get("subscribed"), bool) else None,
            )
            for product in (products if isinstance(products, list) else [])
            if isinstance(product, dict) and isinstance(product.get("type"), str)
        ),
    )


def get_billing_summary_for_app_context(
    request: HttpRequest, user: "User", user_permissions: "UserPermissions"
) -> BillingSummary | None:
    """A summary of the cached `GET /api/billing` response for the user's current organization, or None.

    It never calls the billing service. It applies the same gates as that endpoint for a session user,
    so the app context does not show billing data that the endpoint would refuse.
    """
    team = user.team
    if team is None:
        return None

    license = get_cached_instance_license()
    if not license or not license.is_v2_license:
        return None

    membership = user_permissions.organization_memberships.get(team.organization_id)
    if membership is None:
        return None
    if user_permissions.current_team.effective_membership_level is None:
        return None

    cached = get_cached_billing_response(team.organization_id, membership.level)
    if cached is None:
        return None

    organization = team.organization
    if has_active_v1_billing(organization):
        return None
    if missing_two_factor_step(request, user) is not None:
        return None
    if not is_impersonated_session(request) and OrganizationDomain.objects.is_email_blocked_by_domain_enforcement(
        user.email, organization
    ):
        return None

    return summarize_billing_response(cached)
