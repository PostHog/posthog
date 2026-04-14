"""Salesforce stripe/billing enrichment workflow.

Pushes Stripe customer data (customer id + billing address) and internal
``billing_customer.name`` onto Salesforce Account records. Runs daily with a
Redis-backed high-water mark so only rows that changed in the duckling DWH since
the last successful run are touched. The first run (or any run after watermark
eviction) performs a full backfill.
"""

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
    SALESFORCE_UPDATE_BATCH_SIZE,
    STRIPE_ENRICHMENT_FIELD_MAPPINGS,
    STRIPE_ENRICHMENT_PAGE_SIZE,
)
from ee.billing.salesforce_enrichment.enrichment import bulk_update_salesforce_accounts
from ee.billing.salesforce_enrichment.redis_cache import (
    get_stripe_enrichment_watermark,
    set_stripe_enrichment_watermark,
)
from ee.billing.salesforce_enrichment.salesforce_client import get_salesforce_client
from ee.billing.salesforce_enrichment.stripe_signals import StripeSignals, fetch_stripe_signals

LOGGER = get_logger(__name__)

# SOQL IN clauses are limited by query length, not cardinality. 200 is comfortably
# under the 100k-character SOQL limit for UUID-sized org ids and matches the
# sObject Collections update batch size, keeping the two loops symmetrical.
_SFDC_LOOKUP_CHUNK_SIZE = 200


def _soql_quote(value: str) -> str:
    """Escape a string for safe inclusion in a SOQL literal.

    Posthog org ids are UUIDs so in practice this is defense-in-depth: any value
    ending up in the ``IN`` clause must not be able to break out of its quotes.
    """
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _compose_billing_street(signals: StripeSignals) -> str | None:
    """Combine Stripe line 1 and line 2 into a single BillingStreet value."""
    parts = [p for p in (signals.address_line_1, signals.address_line_2) if p]
    return "\n".join(parts) if parts else None


def prepare_stripe_update_record(salesforce_account_id: str, signals: StripeSignals) -> dict[str, Any]:
    """Build a single SFDC Account patch payload from a StripeSignals row.

    Only non-``None`` fields are included so a missing Stripe address does not
    accidentally wipe out a manually-curated one in Salesforce.
    """
    record: dict[str, Any] = {"Id": salesforce_account_id}

    for attr, sf_field in STRIPE_ENRICHMENT_FIELD_MAPPINGS.items():
        value = getattr(signals, attr, None)
        if value is not None:
            record[sf_field] = value

    billing_street = _compose_billing_street(signals)
    if billing_street is not None:
        record["BillingStreet"] = billing_street

    return record


@dataclasses.dataclass
class StripeEnrichmentState:
    """Continue-As-New state carried across workflow executions."""

    page_offset: int = 0
    total_rows_fetched: int = 0
    total_updated: int = 0
    total_skipped_no_account: int = 0
    error_count: int = 0
    errors: list[str] = dataclasses.field(default_factory=list)
    # ISO-8601 watermark resolved on the first iteration and held constant across
    # continue-as-new iterations so every page of the same logical run scans from
    # the same ``since``.
    resolved_since: str | None = None
    # ISO-8601 max ``last_changed_at`` seen so far this run; committed to Redis
    # only on the final iteration.
    pending_watermark: str | None = None


@dataclasses.dataclass
class StripeEnrichmentInputs:
    """Inputs for the Salesforce stripe enrichment workflow."""

    page_size: int = STRIPE_ENRICHMENT_PAGE_SIZE
    sfdc_batch_size: int = SALESFORCE_UPDATE_BATCH_SIZE
    max_rows: int | None = None  # Optional cap for testing / partial runs
    force_full_refresh: bool = False  # Ignore stored watermark for this run
    state: StripeEnrichmentState | None = None


@dataclasses.dataclass
class StripeEnrichmentResult:
    """Final result surfaced to the Temporal UI."""

    total_rows_fetched: int
    total_updated: int
    total_skipped_no_account: int
    error_count: int
    errors: list[str]
    committed_watermark: str | None


@dataclasses.dataclass
class EnrichStripePageInputs:
    since: str | None  # ISO-8601 watermark, or None for full scan
    offset: int
    page_size: int
    sfdc_batch_size: int


@dataclasses.dataclass
class EnrichStripePageResult:
    rows_fetched: int
    updated: int
    skipped_no_account: int
    errors: list[str]
    max_last_changed_at: str | None  # ISO-8601 of the latest row in this page


@activity.defn
async def get_stripe_watermark_activity() -> str | None:
    """Read the current stripe-enrichment watermark from Redis as an ISO string."""
    close_old_connections()
    watermark = await get_stripe_enrichment_watermark()
    return watermark.isoformat() if watermark else None


@activity.defn
async def commit_stripe_watermark_activity(watermark_iso: str) -> None:
    """Persist a new watermark after a fully successful run."""
    close_old_connections()
    await set_stripe_enrichment_watermark(dt.datetime.fromisoformat(watermark_iso))


@activity.defn
async def enrich_stripe_page_activity(inputs: EnrichStripePageInputs) -> EnrichStripePageResult:
    """Fetch one page of stripe signals from duckling and push updates to Salesforce.

    Matching Account rows are looked up by ``Posthog_Org_ID__c`` — the same join
    key the usage enrichment workflow uses. Rows with no matching account are
    counted and skipped rather than creating new accounts here: account creation
    belongs to the separate harmonic workflow.
    """
    async with Heartbeater() as heartbeater:
        close_old_connections()
        logger = LOGGER.bind(offset=inputs.offset, page_size=inputs.page_size)

        since = dt.datetime.fromisoformat(inputs.since) if inputs.since else None

        signals_rows = await asyncio.to_thread(
            fetch_stripe_signals,
            since,
            inputs.page_size,
            inputs.offset,
        )

        if not signals_rows:
            logger.info("stripe_enrichment_page_empty")
            return EnrichStripePageResult(
                rows_fetched=0,
                updated=0,
                skipped_no_account=0,
                errors=[],
                max_last_changed_at=None,
            )

        signals_by_org: dict[str, StripeSignals] = {s.posthog_organization_id: s for s in signals_rows}
        all_org_ids = list(signals_by_org.keys())
        max_last_changed_at = max(s.last_changed_at for s in signals_rows)

        sf = get_salesforce_client()
        org_to_account_id: dict[str, str] = {}

        for lookup_chunk in batched(all_org_ids, _SFDC_LOOKUP_CHUNK_SIZE):
            in_clause = ",".join(_soql_quote(org_id) for org_id in lookup_chunk)
            # POSTHOG_ORG_ID_FIELD is a trusted constant and org ids are SOQL-escaped above.
            query = f"SELECT Id, {POSTHOG_ORG_ID_FIELD} FROM Account WHERE {POSTHOG_ORG_ID_FIELD} IN ({in_clause})"
            result = await asyncio.to_thread(sf.query_all, query)
            for row in result.get("records", []):
                posthog_org_id = row.get(POSTHOG_ORG_ID_FIELD)
                if posthog_org_id:
                    org_to_account_id[str(posthog_org_id)] = row["Id"]

        skipped_no_account = sum(1 for org_id in all_org_ids if org_id not in org_to_account_id)

        update_records = [
            prepare_stripe_update_record(org_to_account_id[org_id], signals_by_org[org_id])
            for org_id in all_org_ids
            if org_id in org_to_account_id
        ]

        errors: list[str] = []
        updated = 0
        if update_records:
            try:
                success, failed = await asyncio.to_thread(bulk_update_salesforce_accounts, sf, update_records)
                updated = success
                if failed:
                    errors.append(f"sfdc_bulk_update_failed_count={failed}")
            except Exception as e:
                msg = f"Failed to bulk-update Salesforce at offset {inputs.offset}: {e!s}"
                logger.exception(msg)
                errors.append(msg)

        heartbeater.details = (len(signals_rows), updated, skipped_no_account)

        logger.info(
            "stripe_enrichment_page_completed",
            rows_fetched=len(signals_rows),
            updated=updated,
            skipped_no_account=skipped_no_account,
            error_count=len(errors),
        )

        return EnrichStripePageResult(
            rows_fetched=len(signals_rows),
            updated=updated,
            skipped_no_account=skipped_no_account,
            errors=errors,
            max_last_changed_at=max_last_changed_at.isoformat(),
        )


@workflow.defn(name="salesforce-stripe-enrichment")
class SalesforceStripeEnrichmentWorkflow(PostHogWorkflow):
    """Incrementally push Stripe + billing customer data to Salesforce Accounts."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> StripeEnrichmentInputs:
        loaded = json.loads(inputs[0])
        state_data = loaded.pop("state", None)
        state = StripeEnrichmentState(**state_data) if state_data else None
        return StripeEnrichmentInputs(**loaded, state=state)

    @workflow.run
    async def run(self, inputs: StripeEnrichmentInputs) -> dict[str, Any]:
        logger = LOGGER.bind()
        state = inputs.state or StripeEnrichmentState()
        is_first_iteration = inputs.state is None

        page_size = inputs.page_size
        if inputs.max_rows is not None:
            remaining = inputs.max_rows - state.total_rows_fetched
            if remaining <= 0:
                return self._build_result(state)
            page_size = min(page_size, remaining)

        # Resolve the since watermark exactly once, on the first iteration, and
        # carry it through continue-as-new via state so every page scans from an
        # identical cursor.
        if is_first_iteration and not inputs.force_full_refresh:
            state.resolved_since = await workflow.execute_activity(
                get_stripe_watermark_activity,
                start_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        since = None if inputs.force_full_refresh else state.resolved_since

        logger.info(
            "stripe_enrichment_iteration_started",
            page_offset=state.page_offset,
            page_size=page_size,
            since=since,
            force_full_refresh=inputs.force_full_refresh,
        )

        page_result = await workflow.execute_activity(
            enrich_stripe_page_activity,
            EnrichStripePageInputs(
                since=since,
                offset=state.page_offset,
                page_size=page_size,
                sfdc_batch_size=inputs.sfdc_batch_size,
            ),
            start_to_close_timeout=dt.timedelta(minutes=30),
            heartbeat_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(initial_interval=dt.timedelta(seconds=10), maximum_attempts=3),
        )

        state.total_rows_fetched += page_result.rows_fetched
        state.total_updated += page_result.updated
        state.total_skipped_no_account += page_result.skipped_no_account
        state.error_count += len(page_result.errors)
        # Cap stored errors to avoid unbounded growth across continue-as-new.
        if len(state.errors) < 10:
            state.errors.extend(page_result.errors[: 10 - len(state.errors)])

        if page_result.max_last_changed_at and (
            state.pending_watermark is None or page_result.max_last_changed_at > state.pending_watermark
        ):
            state.pending_watermark = page_result.max_last_changed_at

        reached_max = inputs.max_rows is not None and state.total_rows_fetched >= inputs.max_rows
        is_last_page = page_result.rows_fetched < page_size
        done = is_last_page or reached_max

        if done:
            if state.pending_watermark and not inputs.force_full_refresh:
                await workflow.execute_activity(
                    commit_stripe_watermark_activity,
                    state.pending_watermark,
                    start_to_close_timeout=dt.timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            return self._build_result(state)

        state.page_offset += page_result.rows_fetched
        logger.info(
            "stripe_enrichment_continuing_as_new",
            page_offset=state.page_offset,
            total_rows_fetched=state.total_rows_fetched,
            total_updated=state.total_updated,
        )
        workflow.continue_as_new(
            StripeEnrichmentInputs(
                page_size=inputs.page_size,
                sfdc_batch_size=inputs.sfdc_batch_size,
                max_rows=inputs.max_rows,
                force_full_refresh=inputs.force_full_refresh,
                state=state,
            )
        )

    @staticmethod
    def _build_result(state: StripeEnrichmentState) -> dict[str, Any]:
        return dataclasses.asdict(
            StripeEnrichmentResult(
                total_rows_fetched=state.total_rows_fetched,
                total_updated=state.total_updated,
                total_skipped_no_account=state.total_skipped_no_account,
                error_count=state.error_count,
                errors=state.errors[:10],
                committed_watermark=state.pending_watermark,
            )
        )
