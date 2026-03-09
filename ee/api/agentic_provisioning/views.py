from __future__ import annotations

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
# Service catalog — fetched from the billing service and mapped to the
# APP 0.1d services format with `stripe_price` pricing.
# ---------------------------------------------------------------------------

SERVICES_CACHE_KEY = "agentic_provisioning:services"
SERVICES_CACHE_TTL = 300  # 5 minutes

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


def _fetch_services_from_billing() -> list[dict[str, Any]]:
    try:
        res = external_requests.get(
            f"{BILLING_SERVICE_URL}/api/products-v2",
            params={"plan": "standard"},
        )
        res.raise_for_status()
        products = res.json().get("products", [])
    except Exception:
        logger.exception("agentic_provisioning.services.billing_fetch_failed")
        return []

    services = []
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
                    "type": "paid",
                    "paid": {
                        "type": "stripe_price",
                        "stripe_price": paid_plan["price_id"],
                    },
                },
            }
        )

    return services


def _get_services() -> list[dict[str, Any]]:
    cached = cache.get(SERVICES_CACHE_KEY)
    if cached is not None:
        return cached

    services = _fetch_services_from_billing()
    if services:
        cache.set(SERVICES_CACHE_KEY, services, SERVICES_CACHE_TTL)
    return services


VALID_SERVICE_IDS: set[str] = set(_CATEGORY_MAP.keys())


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
