"""Service catalog for GET /provisioning/services - three services:

1. free (plan) - generous free tier, no credit card required
2. pay_as_you_go (plan) - usage-based pricing, no minimum commitment
3. analytics (deployable) - provisions a PostHog project, pricing varies
   by parent plan via component pricing

The built catalog is cached instance-wide (see constants.py), so billing is
hit at most once per TTL regardless of which surface serves the request.
"""

from __future__ import annotations

import time
from typing import Any

from django.core.cache import cache

import requests
import structlog

from ee.partners.stripe.api.provisioning.constants import (
    ALL_CATEGORIES,
    ANALYTICS_SERVICE_ID,
    FREE_PLAN_SERVICE_ID,
    PAY_AS_YOU_GO_SERVICE_ID,
    SERVICES_CACHE_EXPIRES_KEY,
    SERVICES_CACHE_KEY,
    SERVICES_CACHE_RETRY_TTL,
    SERVICES_CACHE_STORE_TTL,
    SERVICES_CACHE_TTL,
)
from ee.settings import BILLING_SERVICE_URL

logger = structlog.get_logger(__name__)

_EXCLUDED_PRODUCT_TYPES = {"platform_and_support", "integrations"}

# (connect, read) timeout so a hung billing service can't pin a worker while
# the cached/static fallback is available.
_BILLING_FETCH_TIMEOUT = (2, 10)

_FALLBACK_DESCRIPTION = "PostHog — AI infrastructure for your product: product & web analytics, session replay, feature flags & experiments, error tracking, AI observability, logs & traces, and more."


def _build_free_plan_service() -> dict[str, Any]:
    return {
        "id": FREE_PLAN_SERVICE_ID,
        "description": "Free - generous free tier across all PostHog products, no credit card required.",
        "categories": ALL_CATEGORIES,
        "pricing": {"type": "free"},
        "kind": "plan",
        "allowed_updates": [PAY_AS_YOU_GO_SERVICE_ID],
    }


def _build_pay_as_you_go_service() -> dict[str, Any]:
    return {
        "id": PAY_AS_YOU_GO_SERVICE_ID,
        "description": "Pay-as-you-go - usage-based pricing across all PostHog products with no minimum commitment.",
        "categories": ALL_CATEGORIES,
        "pricing": {
            "type": "paid",
            "paid": {
                "type": "freeform",
                "freeform": "$0/mo base, usage-based pricing, generous free tier. See https://posthog.com/pricing for rates.",
            },
        },
        "kind": "plan",
        "allowed_updates": [FREE_PLAN_SERVICE_ID],
    }


def _build_analytics_service(description: str) -> dict[str, Any]:
    return {
        "id": ANALYTICS_SERVICE_ID,
        "description": description,
        "categories": ALL_CATEGORIES,
        "pricing": {
            "type": "component",
            "component": {
                "options": [
                    {"parent_service_ids": [FREE_PLAN_SERVICE_ID], "type": "free"},
                    {
                        "parent_service_ids": [PAY_AS_YOU_GO_SERVICE_ID],
                        "type": "paid",
                        "paid": {"type": "freeform", "freeform": "Usage-based pricing, pay only for what you use."},
                    },
                ]
            },
        },
        "kind": "deployable",
        # Stripe validates allowed_updates client-side before calling update_service.
        # Without this, `stripe projects update` rejects plan changes.
        "allowed_updates": ["service_ref"],
    }


def _fetch_services_from_billing() -> list[dict[str, Any]] | None:
    """Fetch product catalog from billing and build the service list."""
    try:
        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/products-v2",
            params={"plan": "standard"},
            timeout=_BILLING_FETCH_TIMEOUT,
        )
        res.raise_for_status()
        products = res.json().get("products", [])
    except Exception:
        logger.exception("stripe_provisioning.services.billing_fetch_failed")
        return None

    # TODO: latent bug - this transform sits outside the try, so a malformed
    # product payload (non-dict entries) raises and 500s the endpoint instead
    # of returning None to trigger the fallback; an empty or fully filtered
    # product list also produces a description with an empty product listing.
    product_names = [
        p.get("name", "")
        for p in products
        if p.get("type", "") not in _EXCLUDED_PRODUCT_TYPES and not p.get("inclusion_only")
    ]
    description = f"PostHog — {', '.join(n for n in product_names if n).lower()}, and more."

    return [_build_free_plan_service(), _build_pay_as_you_go_service(), _build_analytics_service(description)]


def get_services() -> list[dict[str, Any]]:
    cached = cache.get(SERVICES_CACHE_KEY)
    expires_at = cache.get(SERVICES_CACHE_EXPIRES_KEY)

    now = time.time()
    if cached is not None and expires_at is not None and now < expires_at:
        return cached

    services = _fetch_services_from_billing()
    if services is not None:
        cache.set(SERVICES_CACHE_KEY, services, SERVICES_CACHE_STORE_TTL)
        cache.set(SERVICES_CACHE_EXPIRES_KEY, now + SERVICES_CACHE_TTL, SERVICES_CACHE_STORE_TTL)
        return services

    if cached is not None:
        logger.warning("stripe_provisioning.services.serving_stale_cache")
        cache.set(SERVICES_CACHE_EXPIRES_KEY, now + SERVICES_CACHE_RETRY_TTL, SERVICES_CACHE_STORE_TTL)
        return cached

    logger.warning("stripe_provisioning.services.no_cache_fallback")
    fallback = [
        _build_free_plan_service(),
        _build_pay_as_you_go_service(),
        _build_analytics_service(_FALLBACK_DESCRIPTION),
    ]
    cache.set(SERVICES_CACHE_KEY, fallback, SERVICES_CACHE_RETRY_TTL)
    cache.set(SERVICES_CACHE_EXPIRES_KEY, now + SERVICES_CACHE_RETRY_TTL, SERVICES_CACHE_RETRY_TTL)
    return fallback
