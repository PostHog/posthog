from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from django.conf import settings

import requests
import structlog

logger = structlog.get_logger(__name__)

SHOPIFY_TIMEOUT_SECONDS = 15

# Customer-facing storefront link (differs from the myshopify admin-API domain). This is the same
# link the old Zendesk "Merch / Discount Code Snippet" macro shared with customers.
STOREFRONT_DISCOUNT_URL = "https://shop.posthog.com/discount/{code}"

_DISCOUNT_MUTATION = """
mutation MerchCode($input: DiscountCodeBasicInput!) {
  discountCodeBasicCreate(basicCodeDiscount: $input) {
    codeDiscountNode { id }
    userErrors { field message code }
  }
}
""".strip()


class MerchCodeError(Exception):
    """A merch code could not be created."""


class MerchCodeNotConfigured(MerchCodeError):
    """The Shopify access token / hash key have not been provisioned."""


def derive_merch_code(context: str, iso_timestamp: str, hash_key: str) -> str:
    """Derive a 12-char discount code from context + timestamp, salted with the secret hash key.

    Kept byte-identical to HogHero and jokerhog (`sha256("{base}-{hash_key}")[:12]`) so codes look
    and behave the same across every tool that mints them.
    """
    base = f"{context.replace('/', '-')}-{iso_timestamp}"
    return hashlib.sha256(f"{base}-{hash_key}".encode()).hexdigest()[:12]


def create_merch_code(*, context: str, value_usd: Decimal, usage_limit: int) -> dict[str, Any]:
    """Mint a real Shopify discount code for the PostHog merch store.

    Raises MerchCodeNotConfigured if secrets are missing, MerchCodeError on any Shopify failure.
    """
    token: str = settings.SHOPIFY_MERCH_ACCESS_TOKEN
    hash_key: str = settings.SHOPIFY_MERCH_HASH_KEY
    if not token or not hash_key:
        raise MerchCodeNotConfigured(
            "Shopify merch codes are not configured on this instance "
            "(SHOPIFY_MERCH_ACCESS_TOKEN and SHOPIFY_MERCH_HASH_KEY must be set)."
        )

    iso_timestamp = datetime.now(UTC).isoformat()
    code = derive_merch_code(context, iso_timestamp, hash_key)
    # "{context}:{code}" title makes the discount traceable back to its ticket in Shopify admin.
    title = f"{context}:{code}"

    variables = {
        "input": {
            "title": title,
            "code": code,
            "startsAt": iso_timestamp,
            "customerSelection": {"all": True},
            "customerGets": {
                "value": {"discountAmount": {"amount": f"{value_usd:.2f}", "appliesOnEachItem": False}},
                "items": {"all": True},
            },
            "appliesOncePerCustomer": True,
            "usageLimit": usage_limit,
        }
    }

    url = f"https://{settings.SHOPIFY_MERCH_STORE_DOMAIN}/admin/api/{settings.SHOPIFY_MERCH_API_VERSION}/graphql.json"
    try:
        response = requests.post(
            url,
            json={"query": _DISCOUNT_MUTATION, "variables": variables},
            headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
            timeout=SHOPIFY_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as e:
        raise MerchCodeError(f"Shopify request failed: {e}") from e
    except ValueError as e:
        raise MerchCodeError("Shopify returned a non-JSON response.") from e

    if payload.get("errors"):
        raise MerchCodeError(f"Shopify returned errors: {payload['errors']}")

    result = (payload.get("data") or {}).get("discountCodeBasicCreate") or {}
    user_errors = result.get("userErrors") or []
    if user_errors:
        raise MerchCodeError(f"Shopify rejected the discount: {user_errors}")

    gid: str = (result.get("codeDiscountNode") or {}).get("id") or ""
    discount_id = gid.rsplit("/", 1)[-1] if gid else ""

    return {
        "code": code,
        "value_usd": value_usd,
        "usage_limit": usage_limit,
        "discount_url": STOREFRONT_DISCOUNT_URL.format(code=code),
        "admin_url": f"https://admin.shopify.com/store/posthog/discounts/{discount_id}" if discount_id else None,
    }
