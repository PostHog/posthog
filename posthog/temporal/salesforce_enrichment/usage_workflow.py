"""Salesforce usage enrichment workflow - enriches accounts with PostHog usage signals."""

import json
import time
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
    POSTHOG_FETCH_MAPPINGS_PAGE_SIZE,
    POSTHOG_ORG_ID_FIELD,
    POSTHOG_USAGE_ENRICHMENT_BATCH_SIZE,
    POSTHOG_USAGE_FIELD_MAPPINGS,
    SALESFORCE_UPDATE_BATCH_SIZE,
)
from ee.billing.salesforce_enrichment.redis_cache import (
    get_cached_org_mappings_count,
    get_org_mappings_page_from_redis,
    store_org_mappings_in_redis,
)
from ee.billing.salesforce_enrichment.salesforce_client import get_salesforce_client
from ee.billing.salesforce_enrichment.usage_signals import UsageSignals, aggregate_usage_signals_for_orgs

LOGGER = get_logger(__name__)

# Fields from POSTHOG_USAGE_FIELD_MAPPINGS that are handled specially (not simple attribute->field copy)
_SPECIAL_FIELDS = frozenset({"products_activated_7d", "products_activated_30d"})


@dataclasses.dataclass
class UsageEnrichmentState:
    """Continue-As-New state carried across workflow executions."""

    page_offset: int = 0
    total_processed: int = 0
    total_updated: int = 0
    error_count: int = 0
    errors: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class UsageEnrichmentInputs:
    """Inputs for the usage enrichment workflow."""

    batch_size: int = POSTHOG_USAGE_ENRICHMENT_BATCH_SIZE
    max_orgs: int | None = None  # Optional limit for testing
    specific_org_id: str | None = None  # Debug mode: enrich single org
    state: UsageEnrichmentState | None = None  # Continue-As-New state


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


@dataclasses.dataclass
class EnrichPageResult:
    """Result of enriching one page of org mappings."""

    page_size: int
    processed: int
    updated: int
    errors: list[str]


@activity.defn
async def enrich_org_page_activity(offset: int, limit: int, batch_size: int) -> EnrichPageResult:
    """Read a page of org mappings from Redis, aggregate signals, and update Salesforce.

    All heavy data stays in Redis and within the activity — only small counts
    pass through Temporal's gRPC layer.
    """
    async with Heartbeater() as heartbeater:
        close_old_connections()
        logger = LOGGER.bind()

        # Read mappings directly from Redis
        redis_start = time.monotonic()
        cached_mappings = await get_org_mappings_page_from_redis(offset, limit)
        redis_duration_ms = (time.monotonic() - redis_start) * 1000

        if cached_mappings is None:
            logger.warning(
                "org_mappings_cache_miss",
                reason="cache_expired_or_missing",
                redis_duration_ms=round(redis_duration_ms, 1),
            )
            return EnrichPageResult(page_size=0, processed=0, updated=0, errors=[])

        if not cached_mappings:
            return EnrichPageResult(page_size=0, processed=0, updated=0, errors=[])

        org_to_sf = {m["posthog_org_id"]: m["salesforce_account_id"] for m in cached_mappings}
        all_org_ids = list(org_to_sf.keys())
        total_orgs = len(all_org_ids)

        logger.info(
            "enrich_page_started",
            offset=offset,
            page_size=total_orgs,
            redis_duration_ms=round(redis_duration_ms, 1),
        )

        total_processed = 0
        total_updated = 0
        errors: list[str] = []
        sf = get_salesforce_client()

        for batch_tuple in batched(all_org_ids, batch_size):
            batch_org_ids = list(batch_tuple)
            try:
                # Aggregate usage signals
                signals = await asyncio.to_thread(aggregate_usage_signals_for_orgs, batch_org_ids)

                # Prepare and send Salesforce updates
                update_records = [
                    prepare_salesforce_update_record(org_to_sf[org_id], org_signals)
                    for org_id, org_signals in signals.items()
                    if org_id in org_to_sf
                ]

                if update_records:
                    for sf_batch in batched(update_records, SALESFORCE_UPDATE_BATCH_SIZE):
                        response = await asyncio.to_thread(sf.bulk.Account.update, list(sf_batch))  # type: ignore[union-attr,arg-type]
                        for result in response:
                            if result.get("success"):
                                total_updated += 1
                            else:
                                logger.warning(
                                    "salesforce_account_update_failed",
                                    account_id=result.get("id"),
                                    errors=result.get("errors"),
                                )

                total_processed += len(batch_org_ids)
                heartbeater.details = (total_processed, total_orgs, total_updated)

            except Exception as e:
                error_msg = f"Failed to process batch at offset {offset}: {e!s}"
                logger.exception(error_msg)
                errors.append(error_msg)

        logger.info(
            "enrich_page_completed",
            offset=offset,
            page_size=len(all_org_ids),
            processed=total_processed,
            updated=total_updated,
            error_count=len(errors),
        )

        return EnrichPageResult(
            page_size=len(cached_mappings),
            processed=total_processed,
            updated=total_updated,
            errors=errors,
        )


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
        """Run in production mode, processing mapped organizations one page at a time.

        Uses Continue-As-New to keep event history bounded. Each execution processes
        one page of org mappings via a single activity that reads from Redis internally,
        so no large data passes through Temporal's gRPC layer.
        """
        logger = LOGGER.bind()
        state = inputs.state or UsageEnrichmentState()
        page_size = POSTHOG_FETCH_MAPPINGS_PAGE_SIZE

        # Apply max_orgs limit
        if inputs.max_orgs:
            remaining = inputs.max_orgs - state.total_processed
            if remaining <= 0:
                return self._build_result(state)
            page_size = min(page_size, remaining)

        # Cache org mappings in Redis on the first execution only
        if state.page_offset == 0:
            await workflow.execute_activity(
                cache_org_mappings_activity,
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

        # Enrich one page: reads from Redis, aggregates signals, updates Salesforce
        page_result = await workflow.execute_activity(
            enrich_org_page_activity,
            args=[state.page_offset, page_size, inputs.batch_size],
            start_to_close_timeout=dt.timedelta(minutes=30),
            retry_policy=RetryPolicy(initial_interval=dt.timedelta(seconds=10), maximum_attempts=3),
            heartbeat_timeout=dt.timedelta(minutes=5),
        )

        state.total_processed += page_result.processed
        state.total_updated += page_result.updated
        state.error_count += len(page_result.errors)
        # Cap stored errors to avoid unbounded growth across Continue-As-New executions
        if len(state.errors) < 10:
            state.errors.extend(page_result.errors[: 10 - len(state.errors)])

        # No data or last page — return final result
        if page_result.page_size == 0 or page_result.page_size < page_size:
            if state.page_offset == 0 and page_result.page_size == 0:
                logger.info("no_salesforce_accounts_found")
            return self._build_result(state)

        # More pages to process — continue as new execution
        state.page_offset += page_result.page_size
        logger.info(
            "continuing_as_new",
            page_offset=state.page_offset,
            total_processed=state.total_processed,
            total_updated=state.total_updated,
        )
        workflow.continue_as_new(
            UsageEnrichmentInputs(
                batch_size=inputs.batch_size,
                max_orgs=inputs.max_orgs,
                state=state,
            )
        )

    @staticmethod
    def _build_result(state: UsageEnrichmentState) -> dict[str, Any]:
        return dataclasses.asdict(
            UsageEnrichmentResult(
                total_orgs_processed=state.total_processed,
                total_orgs_updated=state.total_updated,
                error_count=state.error_count,
                errors=state.errors[:10],
            )
        )
