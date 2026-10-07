"""Salesforce usage enrichment workflow - enriches accounts with PostHog usage signals."""

import enum
import json
import time
import asyncio
import datetime as dt
import dataclasses
from collections import Counter
from itertools import batched
from typing import TYPE_CHECKING, Any

from django.db import close_old_connections

from simple_salesforce.format import format_soql
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

from ee.billing.salesforce_enrichment.constants import (
    ORG_MAPPINGS_CACHE_MISSING_ERROR_TYPE,
    POSTHOG_FETCH_MAPPINGS_PAGE_SIZE,
    POSTHOG_ORG_ID_FIELD,
    POSTHOG_ORG_REGION_FIELD,
    POSTHOG_USAGE_ENRICHMENT_BATCH_SIZE,
    POSTHOG_USAGE_FIELD_MAPPINGS,
    SALESFORCE_MOMENTUM_MAX,
    SALESFORCE_UPDATE_BATCH_SIZE,
)
from ee.billing.salesforce_enrichment.org_regions import fetch_org_regions, normalize_org_id
from ee.billing.salesforce_enrichment.redis_cache import (
    OrgMappingsCacheMissingError,
    get_cached_org_mappings_count,
    get_org_mappings_page,
    store_org_mappings_in_redis,
)
from ee.billing.salesforce_enrichment.salesforce_client import get_salesforce_client
from ee.billing.salesforce_enrichment.usage_signals import UsageSignals, aggregate_usage_signals_for_orgs

if TYPE_CHECKING:
    from simple_salesforce import Salesforce

LOGGER = get_logger(__name__)

# Fields from POSTHOG_USAGE_FIELD_MAPPINGS that are handled specially (not simple attribute->field copy)
_SPECIAL_FIELDS = frozenset({"products_activated_7d", "products_activated_30d"})
_MOMENTUM_FIELDS = frozenset({"events_7d_momentum", "events_30d_momentum"})


@dataclasses.dataclass(frozen=False)
class UsageEnrichmentState:
    """Continue-As-New state carried across workflow executions."""

    page_offset: int = 0
    total_processed: int = 0
    total_updated: int = 0
    error_count: int = 0
    errors: list[str] = dataclasses.field(default_factory=list)
    regions_filled: int = 0
    regions_replaced: int = 0


@dataclasses.dataclass
class UsageEnrichmentInputs:
    """Inputs for the usage enrichment workflow."""

    batch_size: int = POSTHOG_USAGE_ENRICHMENT_BATCH_SIZE
    max_orgs: int | None = None  # Optional limit for testing
    specific_org_id: str | None = None  # Debug mode: enrich single org
    state: UsageEnrichmentState | None = None  # Continue-As-New state


@dataclasses.dataclass(frozen=True)
class UsageEnrichmentResult:
    """Result of the usage enrichment workflow."""

    total_orgs_processed: int
    total_orgs_updated: int
    error_count: int
    errors: list[str]
    regions_filled: int
    regions_replaced: int


def prepare_salesforce_update_record(salesforce_account_id: str, signals: UsageSignals) -> dict[str, Any]:
    """Prepare a Salesforce update record from usage signals (None values excluded, except momentum)."""
    record: dict[str, Any] = {"Id": salesforce_account_id}

    for attr, sf_field in POSTHOG_USAGE_FIELD_MAPPINGS.items():
        if attr in _SPECIAL_FIELDS:
            continue
        value = getattr(signals, attr, None)
        if attr in _MOMENTUM_FIELDS:
            # An explicit null clears the field. A skipped field keeps the value of the previous run.
            record[sf_field] = None if value is None else min(value, SALESFORCE_MOMENTUM_MAX)
        elif value is not None:
            record[sf_field] = value

    # Products activated (comma-separated, sorted for consistency)
    record[POSTHOG_USAGE_FIELD_MAPPINGS["products_activated_7d"]] = ",".join(sorted(signals.products_activated_7d))
    record[POSTHOG_USAGE_FIELD_MAPPINGS["products_activated_30d"]] = ",".join(sorted(signals.products_activated_30d))

    return record


class OrgRegionOutcome(enum.StrEnum):
    FILL = "fill"
    MATCHES = "matches"
    REPLACE = "replace"
    RESTAMPED = "restamped"


@frozen
class SalesforceAccountRegion:
    """Values an Account carries when it is re-read just before its batch is written."""

    posthog_org_id: str | None
    region: str | None


def decide_org_region(org_id: str, billing_region: str, current: SalesforceAccountRegion | None) -> OrgRegionOutcome:
    """Decide whether billing's region may be written onto the Account mapped to ``org_id``.

    ``current`` is read just before the write, because the cached mapping can be hours old.
    Billing's license is the authoritative source, so it fills an empty region and replaces
    a different one, such as an interim value copied from Vitally. It writes only onto an
    Account that still carries ``org_id``. The read and the Bulk API write are separate calls
    with no conditional update between them, so a restamp that lands in that gap can take
    the old organization's region until the next run replaces it.
    """
    if current is None or normalize_org_id(current.posthog_org_id) != normalize_org_id(org_id):
        return OrgRegionOutcome.RESTAMPED
    if not current.region:
        return OrgRegionOutcome.FILL
    if current.region == billing_region:
        return OrgRegionOutcome.MATCHES
    return OrgRegionOutcome.REPLACE


def org_region_field_is_writable(sf: "Salesforce") -> bool:
    describe = sf.restful("sobjects/Account/describe") or {}
    return any(
        field["name"] == POSTHOG_ORG_REGION_FIELD and field["updateable"] for field in describe.get("fields", [])
    )


async def _fetch_billing_regions(sf: "Salesforce", org_ids: list[str]) -> dict[str, str]:
    """Return billing's region per normalized organization ID, or an empty map while Salesforce cannot take it.

    Salesforce rejects a whole record that names a missing or read-only field, so
    sending the region before the field is deployed and granted to this integration
    user would also drop the usage fields of every Account that has no region yet.
    """
    logger = LOGGER.bind()
    try:
        if not await asyncio.to_thread(org_region_field_is_writable, sf):
            logger.warning("salesforce_org_region_field_not_writable", field=POSTHOG_ORG_REGION_FIELD)
            return {}
        return await asyncio.to_thread(fetch_org_regions, org_ids)
    except Exception:
        logger.exception("org_region_lookup_failed", org_count=len(org_ids))
        return {}


def read_account_regions(sf: "Salesforce", account_ids: list[str]) -> dict[str, SalesforceAccountRegion]:
    # The field names are trusted constants; simple_salesforce quotes the IN values.
    query = format_soql(
        f"SELECT Id, {POSTHOG_ORG_ID_FIELD}, {POSTHOG_ORG_REGION_FIELD} FROM Account WHERE Id IN {{}}",
        account_ids,
    )
    # Index instead of .get(): a missing key means the query and the field disagree, so
    # the read fails and the batch skips regions instead of deciding on a guessed value.
    return {
        record["Id"]: SalesforceAccountRegion(
            posthog_org_id=record[POSTHOG_ORG_ID_FIELD], region=record[POSTHOG_ORG_REGION_FIELD]
        )
        for record in sf.query_all(query).get("records", [])
    }


@frozen
class _RegionDecision:
    outcome: OrgRegionOutcome
    previous_region: str | None


async def _add_org_regions(
    sf: "Salesforce",
    records: list[dict[str, Any]],
    org_by_account_id: dict[str, str],
    billing_regions: dict[str, str],
) -> dict[str, _RegionDecision]:
    """Add billing's region to each update record whose Account may take it, and return the decision per Account."""
    logger = LOGGER.bind()
    region_by_account_id: dict[str, str] = {}
    for record in records:
        billing_region = billing_regions.get(normalize_org_id(org_by_account_id[record["Id"]]))
        if billing_region is not None:
            region_by_account_id[record["Id"]] = billing_region
    if not region_by_account_id:
        return {}

    try:
        current_by_account_id = await asyncio.to_thread(read_account_regions, sf, list(region_by_account_id))
    except Exception:
        logger.exception("salesforce_account_regions_read_failed", account_count=len(region_by_account_id))
        return {}

    decisions: dict[str, _RegionDecision] = {}
    for record in records:
        account_id = record["Id"]
        billing_region = region_by_account_id.get(account_id)
        if billing_region is None:
            continue
        current = current_by_account_id.get(account_id)
        outcome = decide_org_region(org_by_account_id[account_id], billing_region, current)
        decisions[account_id] = _RegionDecision(outcome=outcome, previous_region=current.region if current else None)
        if outcome in (OrgRegionOutcome.FILL, OrgRegionOutcome.REPLACE):
            record[POSTHOG_ORG_REGION_FIELD] = billing_region
    return decisions


@frozen
class _AccountUpdateCounts:
    updated: int
    regions_filled: int
    regions_replaced: int
    error: str | None = None


async def _update_accounts(
    sf: "Salesforce", records: list[dict[str, Any]], region_decisions: dict[str, _RegionDecision]
) -> _AccountUpdateCounts:
    """Send one Bulk API batch and count the Accounts it updated.

    Salesforce rejects a whole record when one of its values fails, for example a picklist
    value that the Account's record type does not allow. A rejected record that carries the
    region is sent again without it, so a region problem never also drops the usage fields.
    """
    logger = LOGGER.bind()
    updated = 0
    regions_filled = 0
    regions_replaced = 0
    resend: list[dict[str, Any]] = []
    response = await asyncio.to_thread(sf.bulk.Account.update, records)  # type: ignore[union-attr,arg-type]
    # Bulk API results come back in input order, and a failed result can have no id.
    for record, result in zip(records, response, strict=True):
        if result.get("success"):
            updated += 1
            decision = region_decisions.get(record["Id"])
            if decision is None:
                continue
            if decision.outcome is OrgRegionOutcome.FILL:
                regions_filled += 1
            elif decision.outcome is OrgRegionOutcome.REPLACE:
                regions_replaced += 1
                logger.info(
                    "salesforce_org_region_replaced",
                    account_id=record["Id"],
                    previous_region=decision.previous_region,
                    billing_region=record[POSTHOG_ORG_REGION_FIELD],
                )
            continue
        logger.warning("salesforce_account_update_failed", account_id=record["Id"], errors=result.get("errors"))
        if POSTHOG_ORG_REGION_FIELD in record:
            resend.append({field: value for field, value in record.items() if field != POSTHOG_ORG_REGION_FIELD})

    error = None
    if resend:
        try:
            retry_response = await asyncio.to_thread(sf.bulk.Account.update, resend)  # type: ignore[union-attr,arg-type]
        except Exception as e:
            # The first attempt's updates are already written, so a failed resend is reported
            # beside their counts instead of raised over them.
            logger.exception("salesforce_account_resend_failed", account_count=len(resend))
            error = f"Failed to resend {len(resend)} Accounts without the region: {e!s}"
        else:
            rejected = 0
            for record, result in zip(resend, retry_response, strict=True):
                if result.get("success"):
                    updated += 1
                else:
                    rejected += 1
                    logger.warning(
                        "salesforce_account_update_failed", account_id=record["Id"], errors=result.get("errors")
                    )
            if rejected:
                error = f"Salesforce rejected {rejected} Accounts again when resent without the region"
    return _AccountUpdateCounts(
        updated=updated, regions_filled=regions_filled, regions_replaced=regions_replaced, error=error
    )


@activity.defn
async def cache_org_mappings_activity(force_rebuild: bool = False) -> dict[str, Any]:
    """Cache all Salesforce org mappings in Redis (reuses existing cache if available).

    ``force_rebuild`` skips cache reuse and replaces the list unconditionally.
    Recovery from unreadable cache entries needs this: the key still exists, so
    the count check alone would reuse the same bad data.
    """
    close_old_connections()
    logger = LOGGER.bind()

    if force_rebuild:
        logger.info("cache_force_rebuild_querying_salesforce", action="org_mappings")
    else:
        cached_count = await get_cached_org_mappings_count()
        if cached_count is not None:
            logger.info("cache_hit_skipping_salesforce_query", cached_total=cached_count)
            return {"success": True, "total_mappings": cached_count, "cache_reused": True}
        logger.info("cache_miss_querying_salesforce", action="org_mappings")

    sf = get_salesforce_client()
    # POSTHOG_ORG_ID_FIELD is a trusted constant defined in constants.py, not user input.
    # ORDER BY keeps list order deterministic across rebuilds, so a workflow resuming
    # at a saved page offset after a mid-run cache rebuild doesn't skip or repeat orgs.
    query = f"SELECT Id, {POSTHOG_ORG_ID_FIELD} FROM Account WHERE {POSTHOG_ORG_ID_FIELD} != null ORDER BY Id"

    result = await asyncio.to_thread(sf.query_all, query)
    mappings = [
        {"salesforce_account_id": r["Id"], "posthog_org_id": r[POSTHOG_ORG_ID_FIELD]}
        for r in result.get("records", [])
        if r.get(POSTHOG_ORG_ID_FIELD)
    ]

    await store_org_mappings_in_redis(mappings)

    logger.info("org_mappings_cached", total_mappings=len(mappings))
    return {"success": True, "total_mappings": len(mappings)}


@dataclasses.dataclass(frozen=True)
class EnrichPageResult:
    """Result of enriching one page of org mappings."""

    page_size: int
    processed: int
    updated: int
    errors: list[str]
    regions_filled: int = 0
    regions_replaced: int = 0


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
        try:
            cached_mappings = await get_org_mappings_page(offset, limit)
        except OrgMappingsCacheMissingError as e:
            logger.warning(
                "org_mappings_cache_miss",
                reason=str(e),
                offset=offset,
                redis_duration_ms=round((time.monotonic() - redis_start) * 1000, 1),
            )
            raise ApplicationError(
                "Org mappings cache is missing or unreadable",
                type=ORG_MAPPINGS_CACHE_MISSING_ERROR_TYPE,
                non_retryable=True,
            ) from e
        redis_duration_ms = (time.monotonic() - redis_start) * 1000

        if not cached_mappings:
            # An empty page past the end of the list means pagination is complete.
            return EnrichPageResult(page_size=0, processed=0, updated=0, errors=[])

        org_to_sf = {m["posthog_org_id"]: m["salesforce_account_id"] for m in cached_mappings}
        org_by_account_id = {account_id: org_id for org_id, account_id in org_to_sf.items()}
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
        regions_filled = 0
        regions_replaced = 0
        region_outcome_counts: Counter[OrgRegionOutcome] = Counter()
        errors: list[str] = []
        sf = get_salesforce_client()
        billing_regions = await _fetch_billing_regions(sf, all_org_ids)

        for batch_tuple in batched(all_org_ids, batch_size, strict=False):
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
                    for sf_batch in batched(update_records, SALESFORCE_UPDATE_BATCH_SIZE, strict=False):
                        batch_records = list(sf_batch)
                        region_decisions = await _add_org_regions(sf, batch_records, org_by_account_id, billing_regions)
                        region_outcome_counts.update(decision.outcome for decision in region_decisions.values())
                        counts = await _update_accounts(sf, batch_records, region_decisions)
                        total_updated += counts.updated
                        regions_filled += counts.regions_filled
                        regions_replaced += counts.regions_replaced
                        if counts.error:
                            errors.append(counts.error)

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
            billing_regions=len(billing_regions),
            region_outcomes=dict(region_outcome_counts),
            regions_filled=regions_filled,
            regions_replaced=regions_replaced,
            error_count=len(errors),
        )

        return EnrichPageResult(
            page_size=len(cached_mappings),
            processed=total_processed,
            updated=total_updated,
            errors=errors,
            regions_filled=regions_filled,
            regions_replaced=regions_replaced,
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
        if inputs.max_orgs is not None:
            remaining = inputs.max_orgs - state.total_processed
            if remaining <= 0:
                return self._build_result(state)
            page_size = min(page_size, remaining)

        # Cache org mappings in Redis on the first execution only
        if state.page_offset == 0:
            cache_result = await self._warm_org_mappings_cache()
            if not cache_result.get("total_mappings"):
                logger.info("no_salesforce_accounts_found")
                return self._build_result(state)

        # Enrich one page: reads from Redis, aggregates signals, updates Salesforce
        try:
            page_result = await self._run_enrich_page(state.page_offset, page_size, inputs.batch_size)
        except ActivityError as e:
            if not (isinstance(e.cause, ApplicationError) and e.cause.type == ORG_MAPPINGS_CACHE_MISSING_ERROR_TYPE):
                raise
            # The org mappings cache can expire or turn unreadable mid-run; force a
            # rebuild once and retry the page instead of failing the enrichment.
            # A second miss propagates.
            logger.warning("org_mappings_cache_missing_rebuilding", page_offset=state.page_offset)
            cache_result = await self._warm_org_mappings_cache(force_rebuild=True)
            if not cache_result.get("total_mappings"):
                logger.info("no_salesforce_accounts_found")
                return self._build_result(state)
            page_result = await self._run_enrich_page(state.page_offset, page_size, inputs.batch_size)

        state.total_processed += page_result.processed
        state.total_updated += page_result.updated
        state.regions_filled += page_result.regions_filled
        state.regions_replaced += page_result.regions_replaced
        state.error_count += len(page_result.errors)
        # Cap stored errors to avoid unbounded growth across Continue-As-New executions
        if len(state.errors) < 10:
            state.errors.extend(page_result.errors[: 10 - len(state.errors)])

        if page_result.page_size < POSTHOG_FETCH_MAPPINGS_PAGE_SIZE:
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
    async def _warm_org_mappings_cache(force_rebuild: bool = False) -> dict[str, Any]:
        return await workflow.execute_activity(
            cache_org_mappings_activity,
            args=[force_rebuild],
            start_to_close_timeout=dt.timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

    @staticmethod
    async def _run_enrich_page(offset: int, page_size: int, batch_size: int) -> EnrichPageResult:
        return await workflow.execute_activity(
            enrich_org_page_activity,
            args=[offset, page_size, batch_size],
            start_to_close_timeout=dt.timedelta(minutes=30),
            retry_policy=RetryPolicy(initial_interval=dt.timedelta(seconds=10), maximum_attempts=3),
            heartbeat_timeout=dt.timedelta(minutes=5),
        )

    @staticmethod
    def _build_result(state: UsageEnrichmentState) -> dict[str, Any]:
        return dataclasses.asdict(
            UsageEnrichmentResult(
                total_orgs_processed=state.total_processed,
                total_orgs_updated=state.total_updated,
                error_count=state.error_count,
                errors=state.errors[:10],
                regions_filled=state.regions_filled,
                regions_replaced=state.regions_replaced,
            )
        )
