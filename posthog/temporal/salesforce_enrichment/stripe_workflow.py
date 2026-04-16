"""Salesforce stripe/billing enrichment workflow.

Pushes Stripe customer data (customer id + billing address) and internal
``billing_customer.name`` onto Salesforce Account records. Runs daily with a
Redis-backed high-water mark so only rows that changed in the duckgres DWH since
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

from simple_salesforce.format import format_soql
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.logger import get_logger

from ee.billing.salesforce_enrichment.constants import (
    POSTHOG_ORG_ID_FIELD,
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

# simple_salesforce sends SOQL as a GET URL parameter, so the HTTP URL/header
# size limit (~16k) applies rather than the 100k SOQL limit. Each UUID org id
# is ~40 chars with quotes and commas, so 200 ids ~ 8k — safely under the cap.
_SFDC_LOOKUP_CHUNK_SIZE = 200


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

    total_rows_fetched: int = 0
    total_updated: int = 0
    total_skipped_no_account: int = 0
    error_count: int = 0
    errors: list[str] = dataclasses.field(default_factory=list)
    # Intra-run keyset cursor for the next page to fetch.
    cursor_last_changed_at: str | None = None
    cursor_org_id: str | None = None
    # Keyset position of the last successfully processed row, advanced only on
    # fully successful pages and committed to Redis at end-of-run.
    pending_watermark_ts: str | None = None
    pending_watermark_org_id: str | None = None
    run_has_failures: bool = False
    committed_watermark_ts: str | None = None
    committed_watermark_org_id: str | None = None


@dataclasses.dataclass
class StripeEnrichmentInputs:
    """Inputs for the Salesforce stripe enrichment workflow."""

    page_size: int = STRIPE_ENRICHMENT_PAGE_SIZE
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
    committed_watermark_ts: str | None
    committed_watermark_org_id: str | None


@dataclasses.dataclass
class EnrichStripePageInputs:
    page_size: int
    cursor_last_changed_at: str | None = None  # ISO-8601 keyset cursor timestamp
    cursor_org_id: str | None = None  # Keyset cursor tiebreaker


@dataclasses.dataclass
class EnrichStripePageResult:
    rows_fetched: int
    updated: int
    skipped_no_account: int
    errors: list[str]
    next_cursor_last_changed_at: str | None  # ISO-8601 cursor for the next page
    next_cursor_org_id: str | None  # Org-id tiebreaker for the next page


@dataclasses.dataclass
class CommitStripeWatermarkInputs:
    last_changed_at: str  # ISO-8601
    posthog_organization_id: str


@activity.defn
async def get_stripe_watermark_activity() -> tuple[str, str] | None:
    """Read the current stripe-enrichment watermark as a keyset position.

    Returns ``(last_changed_at_iso, posthog_organization_id)`` or ``None`` when
    no watermark is set.
    """
    close_old_connections()
    watermark = await get_stripe_enrichment_watermark()
    if watermark is None:
        return None
    last_changed_at, org_id = watermark
    return (last_changed_at.isoformat(), org_id)


@activity.defn
async def commit_stripe_watermark_activity(inputs: CommitStripeWatermarkInputs) -> None:
    """Persist the keyset watermark after a fully successful run."""
    close_old_connections()
    await set_stripe_enrichment_watermark(
        dt.datetime.fromisoformat(inputs.last_changed_at),
        inputs.posthog_organization_id,
    )


@activity.defn
async def enrich_stripe_page_activity(inputs: EnrichStripePageInputs) -> EnrichStripePageResult:
    """Fetch one page of stripe signals from duckgres and push updates to Salesforce.

    Matching Account rows are looked up by ``Posthog_Org_ID__c`` — the same join
    key the usage enrichment workflow uses. Rows with no matching account are
    counted and skipped
    """
    async with Heartbeater() as heartbeater:
        close_old_connections()
        logger = LOGGER.bind(
            page_size=inputs.page_size,
            cursor_ts=inputs.cursor_last_changed_at,
            cursor_org_id=inputs.cursor_org_id,
        )

        cursor: tuple[dt.datetime, str] | None = None
        if inputs.cursor_last_changed_at and inputs.cursor_org_id is not None:
            cursor = (dt.datetime.fromisoformat(inputs.cursor_last_changed_at), inputs.cursor_org_id)

        signals_rows = await asyncio.to_thread(
            fetch_stripe_signals,
            inputs.page_size,
            cursor,
        )

        if not signals_rows:
            logger.info("stripe_enrichment_page_empty")
            return EnrichStripePageResult(
                rows_fetched=0,
                updated=0,
                skipped_no_account=0,
                errors=[],
                next_cursor_last_changed_at=None,
                next_cursor_org_id=None,
            )

        # The SQL orders by (last_changed_at, posthog_organization_id) ASC so the
        # last row's keyset position is both this page's high-water mark and the
        # starting cursor for the next page.
        signals_by_org: dict[str, StripeSignals] = {s.posthog_organization_id: s for s in signals_rows}
        all_org_ids = list(signals_by_org.keys())
        last_row = signals_rows[-1]
        next_cursor_last_changed_at = last_row.last_changed_at.isoformat()
        next_cursor_org_id = last_row.posthog_organization_id

        sf = await asyncio.to_thread(get_salesforce_client)
        org_to_account_id: dict[str, str] = {}

        for lookup_chunk in batched(all_org_ids, _SFDC_LOOKUP_CHUNK_SIZE):
            # POSTHOG_ORG_ID_FIELD is a trusted constant; simple_salesforce quotes the IN values.
            query = format_soql(
                f"SELECT Id, {POSTHOG_ORG_ID_FIELD} FROM Account WHERE {POSTHOG_ORG_ID_FIELD} IN {{}}",
                list(lookup_chunk),
            )
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
            success, failed = await asyncio.to_thread(
                bulk_update_salesforce_accounts,
                sf,
                update_records,
                raise_on_batch_error=True,
            )
            updated = success
            if failed:
                errors.append(f"sfdc_bulk_update_failed_count={failed}")

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
            next_cursor_last_changed_at=next_cursor_last_changed_at,
            next_cursor_org_id=next_cursor_org_id,
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

        # Resolve the prior-run watermark exactly once, on the first iteration,
        # and seed the intra-run cursor from it so every page resumes from that exact keyset position.
        if is_first_iteration and not inputs.force_full_refresh:
            prior_watermark = await workflow.execute_activity(
                get_stripe_watermark_activity,
                start_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if prior_watermark is not None:
                state.cursor_last_changed_at, state.cursor_org_id = prior_watermark

        logger.info(
            "stripe_enrichment_iteration_started",
            total_rows_fetched=state.total_rows_fetched,
            page_size=page_size,
            cursor_ts=state.cursor_last_changed_at,
            cursor_org_id=state.cursor_org_id,
            force_full_refresh=inputs.force_full_refresh,
        )

        page_result = await workflow.execute_activity(
            enrich_stripe_page_activity,
            EnrichStripePageInputs(
                page_size=page_size,
                cursor_last_changed_at=state.cursor_last_changed_at,
                cursor_org_id=state.cursor_org_id,
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

        if page_result.errors:
            state.run_has_failures = True

        if not state.run_has_failures and page_result.next_cursor_last_changed_at and page_result.next_cursor_org_id:
            state.pending_watermark_ts = page_result.next_cursor_last_changed_at
            state.pending_watermark_org_id = page_result.next_cursor_org_id

        reached_max = inputs.max_rows is not None and state.total_rows_fetched >= inputs.max_rows
        is_last_page = page_result.rows_fetched < page_size
        done = is_last_page or reached_max

        if done:
            # A full refresh still commits at the end so the next incremental
            # run resumes where this one finished instead of replaying the
            # entire history from a stale or missing watermark.
            if state.pending_watermark_ts and state.pending_watermark_org_id:
                await workflow.execute_activity(
                    commit_stripe_watermark_activity,
                    CommitStripeWatermarkInputs(
                        last_changed_at=state.pending_watermark_ts,
                        posthog_organization_id=state.pending_watermark_org_id,
                    ),
                    start_to_close_timeout=dt.timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                state.committed_watermark_ts = state.pending_watermark_ts
                state.committed_watermark_org_id = state.pending_watermark_org_id
            return self._build_result(state)

        state.cursor_last_changed_at = page_result.next_cursor_last_changed_at
        state.cursor_org_id = page_result.next_cursor_org_id
        logger.info(
            "stripe_enrichment_continuing_as_new",
            total_rows_fetched=state.total_rows_fetched,
            total_updated=state.total_updated,
            next_cursor_ts=state.cursor_last_changed_at,
        )
        workflow.continue_as_new(
            StripeEnrichmentInputs(
                page_size=inputs.page_size,
                max_rows=inputs.max_rows,
                force_full_refresh=inputs.force_full_refresh,
                state=state,
            )
        )
        # continue_as_new is typed NoReturn so mypy marks this unreachable, but
        # tests mock it as a plain MagicMock — keep the explicit return so mocked
        # runs produce a real result instead of falling through to None.
        return self._build_result(state)  # type: ignore[unreachable]

    @staticmethod
    def _build_result(state: StripeEnrichmentState) -> dict[str, Any]:
        return dataclasses.asdict(
            StripeEnrichmentResult(
                total_rows_fetched=state.total_rows_fetched,
                total_updated=state.total_updated,
                total_skipped_no_account=state.total_skipped_no_account,
                error_count=state.error_count,
                errors=state.errors[:10],
                committed_watermark_ts=state.committed_watermark_ts,
                committed_watermark_org_id=state.committed_watermark_org_id,
            )
        )
