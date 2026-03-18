"""Salesforce usage enrichment workflow - enriches accounts with PostHog usage signals."""

import json
import asyncio
import datetime as dt
import dataclasses
from itertools import batched
from typing import Any

from django.db import close_old_connections

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

from ee.billing.salesforce_enrichment.constants import (
    POSTHOG_ORG_ID_FIELD,
    POSTHOG_USAGE_ENRICHMENT_BATCH_SIZE,
    POSTHOG_USAGE_FIELD_MAPPINGS,
    SALESFORCE_UPDATE_BATCH_SIZE,
)
from ee.billing.salesforce_enrichment.redis_cache import (
    get_cached_org_mappings_count,
    get_org_mappings_from_redis,
    store_org_mappings_in_redis,
)
from ee.billing.salesforce_enrichment.salesforce_client import get_salesforce_client
from ee.billing.salesforce_enrichment.usage_signals import UsageSignals, aggregate_usage_signals_for_orgs

LOGGER = get_logger(__name__)

# Fields from POSTHOG_USAGE_FIELD_MAPPINGS that are handled specially (not simple attribute->field copy)
_SPECIAL_FIELDS = frozenset({"products_activated_7d", "products_activated_30d"})


@dataclasses.dataclass
class SalesforceOrgMapping:
    """Mapping between Salesforce account and PostHog organization."""

    salesforce_account_id: str
    posthog_org_id: str


@dataclasses.dataclass
class SalesforceUsageUpdate:
    """Update to apply to a Salesforce account."""

    salesforce_account_id: str
    signals: UsageSignals


@dataclasses.dataclass
class UsageEnrichmentInputs:
    """Inputs for the usage enrichment workflow."""

    batch_size: int = POSTHOG_USAGE_ENRICHMENT_BATCH_SIZE
    max_orgs: int | None = None  # Optional limit for testing
    specific_org_id: str | None = None  # Debug mode: enrich single org


@dataclasses.dataclass
class UsageEnrichmentResult:
    """Result of the usage enrichment workflow."""

    total_orgs_processed: int
    total_orgs_updated: int
    error_count: int
    errors: list[str]


def prepare_salesforce_update_record(salesforce_account_id: str, signals: UsageSignals) -> dict[str, Any]:
    """Prepare a Salesforce update record from usage signals (None values excluded)."""
    record: dict[str, Any] = {"Id": salesforce_account_id}

    # Add all mapped fields, excluding None values and special fields
    for attr, sf_field in POSTHOG_USAGE_FIELD_MAPPINGS.items():
        if attr in _SPECIAL_FIELDS:
            continue
        value = getattr(signals, attr, None)
        if value is not None:
            record[sf_field] = value

    # Products activated (comma-separated, sorted for consistency)
    record[POSTHOG_USAGE_FIELD_MAPPINGS["products_activated_7d"]] = ",".join(sorted(signals.products_activated_7d))
    record[POSTHOG_USAGE_FIELD_MAPPINGS["products_activated_30d"]] = ",".join(sorted(signals.products_activated_30d))

    return record


@activity.defn
async def cache_org_mappings_activity() -> dict[str, Any]:
    """Cache all Salesforce org mappings in Redis (reuses existing cache if available)."""
    close_old_connections()
    logger = LOGGER.bind()

    cached_count = await get_cached_org_mappings_count()
    if cached_count is not None:
        logger.info("cache_hit_skipping_salesforce_query", cached_total=cached_count)
        return {"success": True, "total_mappings": cached_count, "cache_reused": True}

    logger.info("cache_miss_querying_salesforce", action="org_mappings")

    sf = get_salesforce_client()
    # POSTHOG_ORG_ID_FIELD is a trusted constant defined in constants.py, not user input
    query = f"SELECT Id, {POSTHOG_ORG_ID_FIELD} FROM Account WHERE {POSTHOG_ORG_ID_FIELD} != null"

    result = await asyncio.to_thread(sf.query_all, query)
    mappings = [
        {"salesforce_account_id": r["Id"], "posthog_org_id": r[POSTHOG_ORG_ID_FIELD]}
        for r in result.get("records", [])
        if r.get(POSTHOG_ORG_ID_FIELD)
    ]

    await store_org_mappings_in_redis(mappings)

    logger.info("org_mappings_cached", total_mappings=len(mappings))
    return {"success": True, "total_mappings": len(mappings)}


@activity.defn
async def fetch_salesforce_org_ids_activity() -> list[SalesforceOrgMapping]:
    """Retrieve org mappings from Redis cache."""
    close_old_connections()
    logger = LOGGER.bind()

    cached_mappings = await get_org_mappings_from_redis()

    if cached_mappings is None:
        logger.warning("org_mappings_cache_miss", reason="cache_expired_or_missing")
        return []

    mappings = [
        SalesforceOrgMapping(
            salesforce_account_id=m["salesforce_account_id"],
            posthog_org_id=m["posthog_org_id"],
        )
        for m in cached_mappings
    ]

    logger.info("org_mappings_fetched_from_cache", total_mappings=len(mappings))
    return mappings


@activity.defn
async def aggregate_usage_signals_activity(org_ids: list[str]) -> dict[str, UsageSignals]:
    """Aggregate usage signals from organization group properties for given org IDs."""
    async with Heartbeater():
        close_old_connections()
        logger = LOGGER.bind()
        logger.info("aggregating_usage_signals", org_count=len(org_ids))

        signals = await asyncio.to_thread(aggregate_usage_signals_for_orgs, org_ids)
        logger.info("usage_signals_aggregated", org_count=len(org_ids), signals_count=len(signals))
        return signals


@activity.defn
async def update_salesforce_usage_activity(updates: list[SalesforceUsageUpdate]) -> int:
    """Bulk update Salesforce accounts with usage signals."""
    async with Heartbeater():
        close_old_connections()
        logger = LOGGER.bind()

        if not updates:
            return 0

        sf = get_salesforce_client()
        update_records = [prepare_salesforce_update_record(u.salesforce_account_id, u.signals) for u in updates]

        success_count = 0
        error_count = 0

        for batch in batched(update_records, SALESFORCE_UPDATE_BATCH_SIZE):
            try:
                response = await asyncio.to_thread(sf.bulk.Account.update, list(batch))  # type: ignore[union-attr,arg-type]
                for result in response:
                    if result.get("success"):
                        success_count += 1
                    else:
                        error_count += 1
                        logger.warning(
                            "salesforce_account_update_failed",
                            account_id=result.get("id"),
                            errors=result.get("errors"),
                        )
            except Exception:
                logger.exception("salesforce_batch_update_failed", batch_size=len(batch))
                error_count += len(batch)

        logger.info(
            "salesforce_updates_completed",
            success_count=success_count,
            error_count=error_count,
            total_updates=len(updates),
        )
        return success_count


@workflow.defn(name="salesforce-usage-enrichment")
class SalesforceUsageEnrichmentWorkflow(PostHogWorkflow):
    """Enrich Salesforce accounts with PostHog usage signals."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> UsageEnrichmentInputs:
        loaded = json.loads(inputs[0])
        return UsageEnrichmentInputs(**loaded)

    @workflow.run
    async def run(self, inputs: UsageEnrichmentInputs) -> dict[str, Any]:
        """Run the usage enrichment workflow."""
        logger = LOGGER.bind()
        logger.info(
            "salesforce_usage_enrichment_started",
            batch_size=inputs.batch_size,
            max_orgs=inputs.max_orgs,
            specific_org_id=inputs.specific_org_id,
        )

        if inputs.specific_org_id:
            return await self._run_debug_mode(inputs.specific_org_id)

        return await self._run_production_mode(inputs)

    async def _run_debug_mode(self, org_id: str) -> dict[str, Any]:
        """Run in debug mode for a single organization."""
        logger = LOGGER.bind()
        logger.info("debug_mode_started", org_id=org_id)

        signals = await workflow.execute_activity(
            aggregate_usage_signals_activity,
            [org_id],
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if org_id not in signals:
            return {"mode": "debug", "org_id": org_id, "error": "No signals found for organization"}

        return {"mode": "debug", "org_id": org_id, "signals": dataclasses.asdict(signals[org_id])}

    async def _run_production_mode(self, inputs: UsageEnrichmentInputs) -> dict[str, Any]:
        """Run in production mode, processing all mapped organizations."""
        logger = LOGGER.bind()

        # Cache org mappings in Redis (if not already cached)
        await workflow.execute_activity(
            cache_org_mappings_activity,
            start_to_close_timeout=dt.timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        # Fetch mappings from cache
        mappings = await workflow.execute_activity(
            fetch_salesforce_org_ids_activity,
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not mappings:
            logger.info("no_salesforce_accounts_found")
            return dataclasses.asdict(
                UsageEnrichmentResult(total_orgs_processed=0, total_orgs_updated=0, error_count=0, errors=[])
            )

        if inputs.max_orgs and len(mappings) > inputs.max_orgs:
            logger.info("limiting_to_max_orgs", original_count=len(mappings), max_orgs=inputs.max_orgs)
            # Sort by org_id for deterministic behavior in testing
            mappings = sorted(mappings, key=lambda m: m.posthog_org_id)[: inputs.max_orgs]

        logger.info("salesforce_accounts_to_enrich", count=len(mappings))

        total_processed = 0
        total_updated = 0
        all_errors: list[str] = []

        org_to_sf = {m.posthog_org_id: m.salesforce_account_id for m in mappings}
        all_org_ids = list(org_to_sf.keys())

        for batch_tuple in batched(all_org_ids, inputs.batch_size):
            batch_org_ids = list(batch_tuple)
            try:
                signals = await workflow.execute_activity(
                    aggregate_usage_signals_activity,
                    batch_org_ids,
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    retry_policy=RetryPolicy(initial_interval=dt.timedelta(seconds=10), maximum_attempts=3),
                    heartbeat_timeout=dt.timedelta(minutes=5),
                )

                updates = [
                    SalesforceUsageUpdate(salesforce_account_id=org_to_sf[org_id], signals=org_signals)
                    for org_id, org_signals in signals.items()
                    if org_id in org_to_sf
                ]

                if updates:
                    updated_count = await workflow.execute_activity(
                        update_salesforce_usage_activity,
                        updates,
                        start_to_close_timeout=dt.timedelta(minutes=10),
                        retry_policy=RetryPolicy(initial_interval=dt.timedelta(seconds=10), maximum_attempts=3),
                        heartbeat_timeout=dt.timedelta(minutes=5),
                    )
                    total_updated += updated_count

                total_processed += len(batch_org_ids)

            except Exception as e:
                error_msg = f"Failed to process batch: {e!s}"
                logger.exception(error_msg)
                all_errors.append(error_msg)

        if len(all_errors) > 10:
            logger.warning("error_list_truncated", total_errors=len(all_errors), shown_errors=10)

        return dataclasses.asdict(
            UsageEnrichmentResult(
                total_orgs_processed=total_processed,
                total_orgs_updated=total_updated,
                error_count=len(all_errors),
                errors=all_errors[:10],
            )
        )
