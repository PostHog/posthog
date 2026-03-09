from __future__ import annotations

import time
from typing import Any

from django.core.cache import cache

import structlog
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.security.outbound_proxy import external_requests

from ee.settings import BILLING_SERVICE_URL

from .signature import SUPPORTED_VERSIONS, verify_stripe_signature

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Service catalog — a parent "posthog" service with component children per
# product. Users provision "posthog" and get all products; individual products
# use component pricing with their Stripe price IDs so the orchestrator can
# display pricing info.
# ---------------------------------------------------------------------------

SERVICES_CACHE_KEY = "agentic_provisioning:services"
SERVICES_CACHE_TTL = 3600  # 1 hour
SERVICES_CACHE_RETRY_TTL = 300  # 5 min retry window when billing is down

# Products that shouldn't be listed as provisionable services
_EXCLUDED_PRODUCT_TYPES = {"platform_and_support", "integrations"}

# Billing product type -> APP service categories
_CATEGORY_MAP: dict[str, list[str]] = {
    "product_analytics": ["analytics"],
    "session_replay": ["observability"],
    "feature_flags": ["feature_flags"],
    "surveys": ["analytics"],
    "data_warehouse": ["database"],
    "error_tracking": ["observability"],
    "llm_analytics": ["analytics", "ai"],
    "logs": ["observability"],
    "posthog_ai": ["ai"],
    "realtime_destinations": ["messaging"],
    "workflows_emails": ["email"],
}

POSTHOG_SERVICE_ID = "posthog"

POSTHOG_PARENT_SERVICE: dict[str, Any] = {
    "id": POSTHOG_SERVICE_ID,
    "description": "PostHog — product analytics, session replay, feature flags, A/B testing, surveys, and more",
    "categories": ["analytics", "observability", "feature_flags", "ai"],
    "pricing": {"type": "free"},
}


def _fetch_services_from_billing() -> list[dict[str, Any]] | None:
    """Fetch product catalog from billing. Returns None on failure."""
    try:
        res = external_requests.get(
            f"{BILLING_SERVICE_URL}/api/products-v2",
            params={"plan": "standard"},
        )
        res.raise_for_status()
        products = res.json().get("products", [])
    except Exception:
        logger.exception("agentic_provisioning.services.billing_fetch_failed")
        return None

    services: list[dict[str, Any]] = [POSTHOG_PARENT_SERVICE]
    for product in products:
        product_type = product.get("type", "")
        if product_type in _EXCLUDED_PRODUCT_TYPES:
            continue
        if product.get("inclusion_only"):
            continue

        paid_plan = next((p for p in product.get("plans", []) if p.get("price_id")), None)
        if not paid_plan:
            continue

        services.append(
            {
                "id": product_type,
                "description": product.get("headline") or product.get("description", ""),
                "categories": _CATEGORY_MAP.get(product_type, ["analytics"]),
                "pricing": {
                    "type": "component",
                    "component": {
                        "options": [
                            {
                                "parent_service_ids": [POSTHOG_SERVICE_ID],
                                "type": "paid",
                                "paid": {
                                    "type": "stripe_price",
                                    "stripe_price": paid_plan["price_id"],
                                },
                            }
                        ]
                    },
                },
            }
        )

    return services


SERVICES_CACHE_EXPIRES_KEY = "agentic_provisioning:services:expires_at"
SERVICES_CACHE_STORE_TTL = 86400  # store data for 24h so stale reads work


def _get_services() -> list[dict[str, Any]]:
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

    # Billing failed — serve stale data, retry after SERVICES_CACHE_RETRY_TTL
    if cached is not None:
        logger.warning("agentic_provisioning.services.serving_stale_cache")
        cache.set(SERVICES_CACHE_EXPIRES_KEY, now + SERVICES_CACHE_RETRY_TTL, SERVICES_CACHE_STORE_TTL)
        return cached

    logger.warning("agentic_provisioning.services.no_cache_fallback")
    fallback = [POSTHOG_PARENT_SERVICE]
    cache.set(SERVICES_CACHE_KEY, fallback, SERVICES_CACHE_RETRY_TTL)
    cache.set(SERVICES_CACHE_EXPIRES_KEY, now + SERVICES_CACHE_RETRY_TTL, SERVICES_CACHE_RETRY_TTL)
    return fallback


VALID_SERVICE_IDS: set[str] = {POSTHOG_SERVICE_ID} | set(_CATEGORY_MAP.keys())


# ---------------------------------------------------------------------------
# GET /provisioning/health
# ---------------------------------------------------------------------------


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def provisioning_health(request: Request) -> Response:
    error = verify_stripe_signature(request)
    if error:
        return error

    return Response({"supported_versions": SUPPORTED_VERSIONS, "status": "ok"})


# ---------------------------------------------------------------------------
# GET /provisioning/services
# ---------------------------------------------------------------------------


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def provisioning_services(request: Request) -> Response:
    error = verify_stripe_signature(request)
    if error:
        return error

    return Response({"data": _get_services(), "next_cursor": ""})
