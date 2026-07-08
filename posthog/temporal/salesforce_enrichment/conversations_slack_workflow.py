"""Salesforce Conversations Slack enrichment workflow."""

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
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger
from posthog.temporal.salesforce_enrichment.usage_workflow import cache_org_mappings_activity

from ee.billing.salesforce_enrichment.constants import (
    CONVERSATIONS_SLACK_ENRICHMENT_BATCH_SIZE,
    CONVERSATIONS_SLACK_FIELD_MAPPINGS,
    ORG_MAPPINGS_CACHE_MISSING_ERROR_TYPE,
    POSTHOG_FETCH_MAPPINGS_PAGE_SIZE,
)
from ee.billing.salesforce_enrichment.conversations_signals import (
    ConversationsSlackSignals,
    aggregate_conversations_slack_signals_for_orgs,
)
from ee.billing.salesforce_enrichment.enrichment import bulk_update_salesforce_accounts
from ee.billing.salesforce_enrichment.redis_cache import OrgMappingsCacheMissingError, get_org_mappings_page
from ee.billing.salesforce_enrichment.salesforce_client import get_salesforce_client

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class ConversationsSlackEnrichmentState:
    """Continue-As-New state carried across workflow executions."""

    page_offset: int = 0
    total_processed: int = 0
    total_updated: int = 0
    error_count: int = 0
    errors: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class ConversationsSlackEnrichmentInputs:
    """Inputs for the Conversations Slack enrichment workflow."""

    batch_size: int = CONVERSATIONS_SLACK_ENRICHMENT_BATCH_SIZE
    max_orgs: int | None = None
    specific_org_id: str | None = None
    state: ConversationsSlackEnrichmentState | None = None


@dataclasses.dataclass
class ConversationsSlackEnrichmentResult:
    """Result of the Conversations Slack enrichment workflow."""

    total_orgs_processed: int
    total_orgs_updated: int
    error_count: int
    errors: list[str]


@dataclasses.dataclass
class EnrichConversationsSlackPageResult:
    """Result of enriching one page of org mappings."""

    page_size: int
    processed: int
    updated: int
    errors: list[str]


def prepare_conversations_slack_update_record(
    salesforce_account_id: str, signals: ConversationsSlackSignals
) -> dict[str, Any]:
    """Prepare a Salesforce Account update record from Conversations Slack signals."""
    record: dict[str, Any] = {"Id": salesforce_account_id}

    for attr, sf_field in CONVERSATIONS_SLACK_FIELD_MAPPINGS.items():
        value = getattr(signals, attr, None)
        if value is None:
            continue

        if attr == "last_slack_activity" and isinstance(value, dt.datetime):
            record[sf_field] = value.date().isoformat()
            continue

        record[sf_field] = value

    return record


def _serialize_signals(signals: ConversationsSlackSignals) -> dict[str, Any]:
    serialized = dataclasses.asdict(signals)
    if signals.last_slack_activity is not None:
        serialized["last_slack_activity"] = signals.last_slack_activity.isoformat()
    return serialized


@activity.defn
async def aggregate_conversations_slack_signals_activity(
    org_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Aggregate Conversations Slack signals for given org IDs."""
    async with Heartbeater():
        close_old_connections()
        logger = LOGGER.bind()
        logger.info("aggregating_conversations_slack_signals", org_count=len(org_ids))

        signals = await asyncio.to_thread(aggregate_conversations_slack_signals_for_orgs, org_ids)
        logger.info("conversations_slack_signals_aggregated", org_count=len(org_ids), signals_count=len(signals))
        return {org_id: _serialize_signals(org_signals) for org_id, org_signals in signals.items()}


@activity.defn
async def enrich_conversations_slack_page_activity(
    offset: int,
    limit: int,
    batch_size: int,
) -> EnrichConversationsSlackPageResult:
    """Read a page of org mappings, aggregate Conversations Slack signals, and update Salesforce."""
    async with Heartbeater() as heartbeater:
        close_old_connections()
        logger = LOGGER.bind()

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
            return EnrichConversationsSlackPageResult(page_size=0, processed=0, updated=0, errors=[])

        org_to_sf = {m["posthog_org_id"]: m["salesforce_account_id"] for m in cached_mappings}
        all_org_ids = list(org_to_sf.keys())
        total_orgs = len(all_org_ids)

        logger.info(
            "conversations_slack_enrich_page_started",
            offset=offset,
            page_size=total_orgs,
            redis_duration_ms=round(redis_duration_ms, 1),
        )

        sf = await asyncio.to_thread(get_salesforce_client)
        total_processed = 0
        total_updated = 0
        errors: list[str] = []

        for batch_tuple in batched(all_org_ids, batch_size, strict=False):
            batch_org_ids = list(batch_tuple)
            signals = await asyncio.to_thread(aggregate_conversations_slack_signals_for_orgs, batch_org_ids)
            update_records = [
                prepare_conversations_slack_update_record(org_to_sf[org_id], org_signals)
                for org_id, org_signals in signals.items()
                if org_id in org_to_sf
            ]

            if update_records:
                success, failed = await asyncio.to_thread(
                    bulk_update_salesforce_accounts,
                    sf,
                    update_records,
                    raise_on_batch_error=True,
                )
                total_updated += success
                if failed:
                    errors.append(f"sfdc_bulk_update_failed_count={failed}")

            total_processed += len(batch_org_ids)
            heartbeater.details = (total_processed, total_orgs, total_updated)

        logger.info(
            "conversations_slack_enrich_page_completed",
            offset=offset,
            page_size=total_orgs,
            processed=total_processed,
            updated=total_updated,
            error_count=len(errors),
        )

        return EnrichConversationsSlackPageResult(
            page_size=len(cached_mappings),
            processed=total_processed,
            updated=total_updated,
            errors=errors,
        )


@workflow.defn(name="salesforce-conversations-slack-enrichment")
class SalesforceConversationsSlackEnrichmentWorkflow(PostHogWorkflow):
    """Enrich Salesforce accounts with Conversations Slack support signals."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ConversationsSlackEnrichmentInputs:
        loaded = json.loads(inputs[0])
        state_data = loaded.pop("state", None)
        state = ConversationsSlackEnrichmentState(**state_data) if state_data else None
        return ConversationsSlackEnrichmentInputs(**loaded, state=state)

    @workflow.run
    async def run(self, inputs: ConversationsSlackEnrichmentInputs) -> dict[str, Any]:
        logger = LOGGER.bind()
        logger.info(
            "salesforce_conversations_slack_enrichment_started",
            batch_size=inputs.batch_size,
            max_orgs=inputs.max_orgs,
            specific_org_id=inputs.specific_org_id,
        )

        if inputs.specific_org_id:
            return await self._run_debug_mode(inputs.specific_org_id)

        return await self._run_production_mode(inputs)

    async def _run_debug_mode(self, org_id: str) -> dict[str, Any]:
        logger = LOGGER.bind()
        logger.info("conversations_slack_debug_mode_started", org_id=org_id)

        signals = await workflow.execute_activity(
            aggregate_conversations_slack_signals_activity,
            [org_id],
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if org_id not in signals:
            return {"mode": "debug", "org_id": org_id, "error": "No Conversations Slack signals found"}

        return {"mode": "debug", "org_id": org_id, "signals": signals[org_id]}

    async def _run_production_mode(self, inputs: ConversationsSlackEnrichmentInputs) -> dict[str, Any]:
        logger = LOGGER.bind()
        state = inputs.state or ConversationsSlackEnrichmentState()
        page_size = POSTHOG_FETCH_MAPPINGS_PAGE_SIZE

        if inputs.max_orgs is not None:
            remaining = inputs.max_orgs - state.total_processed
            if remaining <= 0:
                return self._build_result(state)
            page_size = min(page_size, remaining)

        if state.page_offset == 0:
            cache_result = await self._warm_org_mappings_cache()
            if not cache_result.get("total_mappings"):
                logger.info("no_salesforce_accounts_found")
                return self._build_result(state)

        try:
            page_result = await self._run_enrich_page(state.page_offset, page_size, inputs.batch_size)
        except ActivityError as e:
            if not (isinstance(e.cause, ApplicationError) and e.cause.type == ORG_MAPPINGS_CACHE_MISSING_ERROR_TYPE):
                raise
            # The org mappings cache can expire or turn unreadable mid-run; force a
            # rebuild once and retry the page instead of silently truncating the sync.
            # A second miss propagates.
            logger.warning("org_mappings_cache_missing_rebuilding", page_offset=state.page_offset)
            cache_result = await self._warm_org_mappings_cache(force_rebuild=True)
            if not cache_result.get("total_mappings"):
                logger.info("no_salesforce_accounts_found")
                return self._build_result(state)
            page_result = await self._run_enrich_page(state.page_offset, page_size, inputs.batch_size)

        state.total_processed += page_result.processed
        state.total_updated += page_result.updated
        state.error_count += len(page_result.errors)
        if len(state.errors) < 10:
            state.errors.extend(page_result.errors[: 10 - len(state.errors)])

        if page_result.page_size < POSTHOG_FETCH_MAPPINGS_PAGE_SIZE:
            return self._build_result(state)

        state.page_offset += page_result.page_size
        logger.info(
            "conversations_slack_enrichment_continuing_as_new",
            page_offset=state.page_offset,
            total_processed=state.total_processed,
            total_updated=state.total_updated,
        )
        workflow.continue_as_new(
            ConversationsSlackEnrichmentInputs(
                batch_size=inputs.batch_size,
                max_orgs=inputs.max_orgs,
                state=state,
            )
        )
        return self._build_result(state)  # type: ignore[unreachable]

    @staticmethod
    async def _warm_org_mappings_cache(force_rebuild: bool = False) -> dict[str, Any]:
        return await workflow.execute_activity(
            cache_org_mappings_activity,
            args=[force_rebuild],
            start_to_close_timeout=dt.timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

    @staticmethod
    async def _run_enrich_page(offset: int, page_size: int, batch_size: int) -> EnrichConversationsSlackPageResult:
        return await workflow.execute_activity(
            enrich_conversations_slack_page_activity,
            args=[offset, page_size, batch_size],
            start_to_close_timeout=dt.timedelta(minutes=30),
            retry_policy=RetryPolicy(initial_interval=dt.timedelta(seconds=10), maximum_attempts=3),
            heartbeat_timeout=dt.timedelta(minutes=5),
        )

    @staticmethod
    def _build_result(state: ConversationsSlackEnrichmentState) -> dict[str, Any]:
        return dataclasses.asdict(
            ConversationsSlackEnrichmentResult(
                total_orgs_processed=state.total_processed,
                total_orgs_updated=state.total_updated,
                error_count=state.error_count,
                errors=state.errors[:10],
            )
        )
