"""Billing generates contract/entitlements_contract.json. Refresh it by copying billing's
`billing/contract/entitlements_contract.json`, never by editing it here."""

import json
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Any, Literal, TypedDict

from prometheus_client import Gauge

CONTRACT_PATH = Path(__file__).resolve().parent / "contract" / "entitlements_contract.json"
SUPPORTED_SCHEMA_VERSION = 1

BILLING_CONTRACT_UNKNOWN_USAGE_KEYS = Gauge(
    "billing_contract_unknown_usage_keys",
    "Usage keys billing enforces through PostHog that PostHog has no quota resource for, so nothing limits them.",
    ["usage_key"],
    multiprocess_mode="livemax",
)


class UsageKeyContract(TypedDict):
    quota_enforcement: Literal["posthog", "none"]
    quota_enforcement_note: str | None
    products: list[dict[str, str | None]]


class EntitlementsContract(TypedDict):
    schema_version: int
    contract_hash: str
    usage_keys: dict[str, UsageKeyContract]
    limited_features: dict[str, Any]


class BillingContractMismatch(Exception):
    pass


@cache
def load_contract() -> EntitlementsContract:
    with CONTRACT_PATH.open() as f:
        return json.load(f)


def posthog_enforced_usage_keys(contract: EntitlementsContract) -> frozenset[str]:
    return frozenset(key for key, entry in contract["usage_keys"].items() if entry["quota_enforcement"] == "posthog")


def check_billed_resources(
    *, billed: Iterable[str], known: Iterable[str], contract: EntitlementsContract
) -> frozenset[str]:
    """Contract keys PostHog has no resource for are reported, not raised, so a vendored contract that is ahead of
    PostHog doesn't block unrelated work."""
    billed, known = frozenset(billed), frozenset(known)
    enforced = posthog_enforced_usage_keys(contract)
    unknown = enforced - known
    for usage_key in unknown:
        BILLING_CONTRACT_UNKNOWN_USAGE_KEYS.labels(usage_key=usage_key).set(1)
    if billed != enforced & known:
        raise BillingContractMismatch(
            "QuotaResource.billed disagrees with posthog/billing/contract/entitlements_contract.json. "
            f"Billed but not enforced by PostHog in the contract: {sorted(billed - enforced)}. "
            f"Enforced by PostHog in the contract but not billed: {sorted((enforced & known) - billed)}."
        )
    return unknown
