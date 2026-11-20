"""Billing's entitlements snapshot is total: each field replaces PostHog's copy, so an empty feature list or a
withdrawn trust score applies. A structurally invalid snapshot changes nothing."""

from collections.abc import Mapping
from typing import Any, Literal, cast

import structlog
from prometheus_client import Counter, Gauge

from posthog.billing.entitlements_contract import SUPPORTED_SCHEMA_VERSION, load_contract
from posthog.models.organization import Organization

from ee.billing.billing_types import EntitlementsBlock
from ee.billing.quota_limiting import QuotaResource

logger = structlog.get_logger(__name__)

BILLED_USAGE_KEYS = frozenset(resource.value for resource in QuotaResource if resource.billed)

EntitlementField = Literal["usage_limits", "trust_scores", "never_drop_data", "features"]
# A batch sync follows no billing change, so any field it changes was drift.
BATCH_SYNC_TYPE = "batch"

BILLING_CONTRACT_STALE = Gauge(
    "billing_contract_stale",
    "1 when the last entitlements snapshot came from a contract other than the vendored one.",
    multiprocess_mode="livemax",
)
BILLING_SNAPSHOT_REJECTED = Counter(
    "billing_snapshot_rejected",
    "Structurally invalid entitlements snapshots, rejected whole. The organization keeps its previous entitlements.",
    ["reason"],
)
BILLING_SNAPSHOT_MISSING_USAGE_LIMIT = Counter(
    "billing_snapshot_missing_usage_limit",
    "Billed usage keys a snapshot left out. The organization keeps its previous limit for the key.",
    ["usage_key"],
)
BILLING_ENTITLEMENT_LIMIT_SKIPPED = Counter(
    "billing_entitlement_limit_skipped",
    "Limits on billed usage keys that weren't stored, because the organization has no usage entry for the key.",
    ["usage_key"],
)
# Batch syncs also carry real changes: usage-driven limits for payers with dollar limits, grant and trial expiries,
# and config deploys. Only trust_scores and never_drop_data drift on free organizations means something was wrong.
BILLING_ENTITLEMENT_DRIFT_REPAIRED = Counter(
    "billing_entitlement_drift_repaired",
    "Entitlement fields a batch billing sync changed.",
    ["field", "plan_state"],
)


class SnapshotRejected(Exception):
    def __init__(self, reason: Literal["malformed", "unsupported_schema_version"]) -> None:
        super().__init__(reason)
        self.reason = reason


def apply_entitlements(
    organization: Organization, block: object, *, sync_type: str | None = None
) -> frozenset[EntitlementField] | None:
    """Returns the changed fields, or None when the snapshot is rejected. The caller saves.

    Limits go only into usage entries billing sent usage for, because an entry without usage has no period to
    enforce against. A billed key the snapshot leaves out keeps its limit, and everything else applies."""
    try:
        entitlements = validate_entitlements(block)
    except SnapshotRejected as rejected:
        BILLING_SNAPSHOT_REJECTED.labels(reason=rejected.reason).inc()
        logger.warning("billing_entitlements_rejected", organization_id=str(organization.id), reason=rejected.reason)
        return None

    BILLING_CONTRACT_STALE.set(int(entitlements["contract_hash"] != load_contract()["contract_hash"]))
    for usage_key in BILLED_USAGE_KEYS - entitlements["usage_limits"].keys():
        BILLING_SNAPSHOT_MISSING_USAGE_LIMIT.labels(usage_key=usage_key).inc()

    changed: set[EntitlementField] = set()
    if _replace_limits(organization, entitlements["usage_limits"]):
        changed.add("usage_limits")
    if organization.customer_trust_scores != entitlements["trust_scores"]:
        organization.customer_trust_scores = dict(entitlements["trust_scores"])
        changed.add("trust_scores")
    # Compared as booleans: older billing sent None for False, and rewriting one as the other changes nothing.
    if bool(organization.never_drop_data) != entitlements["never_drop_data"]:
        organization.never_drop_data = entitlements["never_drop_data"]
        changed.add("never_drop_data")
    if organization.available_product_features != entitlements["features"]:
        organization.available_product_features = list(entitlements["features"])
        changed.add("features")

    if sync_type == BATCH_SYNC_TYPE:
        for field in changed:
            BILLING_ENTITLEMENT_DRIFT_REPAIRED.labels(field=field, plan_state=entitlements["plan_state"]).inc()
    return frozenset(changed)


def validate_entitlements(block: object) -> EntitlementsBlock:
    if not isinstance(block, Mapping):
        raise SnapshotRejected("malformed")
    if block.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise SnapshotRejected("unsupported_schema_version")
    usage_limits = block.get("usage_limits")
    trust_scores = block.get("trust_scores")
    features = block.get("features")
    if not (
        isinstance(block.get("contract_hash"), str)
        and block.get("plan_state") in ("free", "paid")
        and isinstance(block.get("never_drop_data"), bool)
        and isinstance(usage_limits, dict)
        and all(limit is None or (_is_int(limit) and limit >= 0) for limit in usage_limits.values())
        and isinstance(trust_scores, dict)
        and all(_is_int(score) for score in trust_scores.values())
        and isinstance(features, list)
        and all(isinstance(feature, dict) and isinstance(feature.get("key"), str) for feature in features)
    ):
        raise SnapshotRejected("malformed")
    return cast(EntitlementsBlock, block)


def contract_usage_keys() -> frozenset[str]:
    return frozenset(load_contract()["usage_keys"])


def _replace_limits(organization: Organization, usage_limits: Mapping[str, int | None]) -> bool:
    """A key missing from `usage_limits` keeps its stored limit, so billing running an older contract than PostHog
    doesn't remove limits."""
    usage = cast(dict[str, Any], organization.usage or {})
    changed = False
    for usage_key, limit in usage_limits.items():
        entry = usage.get(usage_key)
        if not (isinstance(entry, dict) and entry):
            if limit is not None and usage_key in BILLED_USAGE_KEYS:
                BILLING_ENTITLEMENT_LIMIT_SKIPPED.labels(usage_key=usage_key).inc()
            continue
        if entry.get("limit") != limit:
            entry["limit"] = limit
            changed = True
    return changed


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
