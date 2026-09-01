"""Experimental measurement-only usage snapshots from billing usage records."""

import time
from collections import defaultdict
from collections.abc import Iterable
from datetime import (
    UTC,
    datetime,
    time as datetime_time,
    timedelta,
)
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

import structlog
from asgiref.sync import sync_to_async
from pydantic import BaseModel
from temporalio import activity, common, workflow
from temporalio.exceptions import ApplicationError

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.ph_client import get_client as get_ph_client
from posthog.tasks.report_utils import capture_event
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater

logger = structlog.get_logger(__name__)

EXPERIMENTAL_REALTIME_USAGE_EVENT = "experimental organization realtime usage report"
MANUAL_EXPERIMENTAL_REALTIME_USAGE_EVENT = "experimental organization realtime usage report manual"
CLICKHOUSE_SETTINGS = {"max_execution_time": 5 * 60}
CAPTURE_BATCH_SIZE = 1000

CaptureMode = Literal["capture", "manual_report", "dry_run"]

CANONICAL_USAGE_QUERY = """
SELECT
    organization_id,
    producer_id,
    usage_key,
    unit,
    sum(quantity) AS quantity
FROM
(
    SELECT
        argMax(organization_id, inserted_at) AS organization_id,
        producer_id,
        usage_key,
        argMax(unit, inserted_at) AS unit,
        argMax(quantity, inserted_at) AS quantity
    FROM billing_usage_records
    WHERE timestamp >= %(period_start)s
      AND timestamp < %(period_end)s
      {organization_filter}
    GROUP BY team_id, toDate(timestamp), producer_id, usage_key, record_id
)
GROUP BY organization_id, producer_id, usage_key, unit
ORDER BY organization_id, producer_id, usage_key, unit
"""


class GatherExperimentalRealtimeUsageInputs(BaseModel):
    day_offset: int = 0
    organization_ids: list[str] | None = None
    mode: CaptureMode = "capture"


class ExperimentalRealtimeUsageContext(BaseModel):
    period_start: datetime
    period_end: datetime
    snapshot_at: datetime
    report_completeness: str
    organization_ids: list[str] | None = None
    mode: CaptureMode = "capture"


class GatherExperimentalRealtimeUsageResult(BaseModel):
    canonical_row_count: int
    organizations_found: int
    organizations_captured: int
    usage_key_count: int
    query_duration_ms: int
    capture_duration_ms: int


class UsageSnapshot(BaseModel):
    organization_id: str
    usage_by_key: dict[str, int]
    unit_by_key: dict[str, str]
    usage_by_producer: dict[str, dict[str, dict[str, int]]]
    unit_conflicts: dict[str, list[str]]


UsageRow = tuple[UUID | str, str, str, str, int]


def build_experimental_realtime_context(
    inputs: GatherExperimentalRealtimeUsageInputs, now: datetime
) -> ExperimentalRealtimeUsageContext:
    report_day = (now.astimezone(UTC) - timedelta(days=inputs.day_offset)).date()
    period_start = datetime.combine(report_day, datetime_time.min, tzinfo=UTC)
    return ExperimentalRealtimeUsageContext(
        period_start=period_start,
        period_end=period_start + timedelta(days=1),
        snapshot_at=now.astimezone(UTC),
        report_completeness="partial" if inputs.day_offset == 0 else "complete",
        organization_ids=inputs.organization_ids,
        mode=inputs.mode,
    )


def get_canonical_usage_rows(ctx: ExperimentalRealtimeUsageContext) -> list[UsageRow]:
    organization_filter = ""
    params: dict[str, object] = {"period_start": ctx.period_start, "period_end": ctx.period_end}
    if ctx.organization_ids:
        organization_filter = "AND organization_id IN %(organization_ids)s"
        params["organization_ids"] = ctx.organization_ids

    with tags_context(product=Product.BILLING, feature=Feature.USAGE_REPORT):
        rows = sync_execute(
            CANONICAL_USAGE_QUERY.format(organization_filter=organization_filter),
            params,
            workload=Workload.OFFLINE,
            settings=CLICKHOUSE_SETTINGS,
            ch_user=ClickHouseUser.BILLING,
        )
    return [
        (organization_id, producer_id, usage_key, unit, int(quantity))
        for organization_id, producer_id, usage_key, unit, quantity in rows
    ]


def build_usage_snapshots(rows: Iterable[UsageRow]) -> list[UsageSnapshot]:
    by_organization: dict[str, list[UsageRow]] = defaultdict(list)
    for organization_id, producer_id, usage_key, unit, quantity in rows:
        by_organization[str(organization_id)].append((organization_id, producer_id, usage_key, unit, quantity))

    snapshots: list[UsageSnapshot] = []
    for organization_id, organization_rows in by_organization.items():
        quantities_by_key_and_unit: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        usage_by_producer: dict[str, dict[str, dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )
        for _, producer_id, usage_key, unit, quantity in organization_rows:
            quantities_by_key_and_unit[usage_key][unit] += quantity
            usage_by_producer[producer_id][usage_key][unit] += quantity

        unit_conflicts = {
            usage_key: sorted(units) for usage_key, units in quantities_by_key_and_unit.items() if len(units) > 1
        }
        usage_by_key = {
            usage_key: next(iter(quantities.values()))
            for usage_key, quantities in quantities_by_key_and_unit.items()
            if len(quantities) == 1
        }
        unit_by_key = {
            usage_key: next(iter(quantities))
            for usage_key, quantities in quantities_by_key_and_unit.items()
            if len(quantities) == 1
        }
        snapshots.append(
            UsageSnapshot(
                organization_id=organization_id,
                usage_by_key=usage_by_key,
                unit_by_key=unit_by_key,
                usage_by_producer={
                    producer_id: {usage_key: dict(units) for usage_key, units in usage.items()}
                    for producer_id, usage in usage_by_producer.items()
                },
                unit_conflicts=unit_conflicts,
            )
        )
    return snapshots


def experimental_usage_event_uuid(organization_id: str, ctx: ExperimentalRealtimeUsageContext) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"experimental-realtime-usage:{organization_id}:{ctx.period_start.isoformat()}:{ctx.period_end.isoformat()}:{ctx.snapshot_at.isoformat()}",
    )


def event_name_for_mode(mode: CaptureMode) -> str:
    if mode == "manual_report":
        return MANUAL_EXPERIMENTAL_REALTIME_USAGE_EVENT
    return EXPERIMENTAL_REALTIME_USAGE_EVENT


def capture_usage_snapshots(
    snapshots: Iterable[UsageSnapshot], ctx: ExperimentalRealtimeUsageContext, event_name: str
) -> int:
    ph_client = get_ph_client(sync_mode=True)
    if ph_client is None:
        return 0

    captured = 0
    for snapshot in snapshots:
        if snapshot.unit_conflicts:
            logger.warning(
                "experimental_realtime_usage.unit_conflict",
                organization_id=snapshot.organization_id,
                unit_conflicts=snapshot.unit_conflicts,
            )
        capture_event(
            pha_client=ph_client,
            name=event_name,
            organization_id=snapshot.organization_id,
            distinct_id=f"org-{snapshot.organization_id}",
            event_uuid=experimental_usage_event_uuid(snapshot.organization_id, ctx),
            properties={
                "experimental": True,
                "schema_version": 1,
                "source": "billing_usage_records",
                "organization_id": snapshot.organization_id,
                "period_start": ctx.period_start.isoformat(),
                "period_end": ctx.period_end.isoformat(),
                "snapshot_at": ctx.snapshot_at.isoformat(),
                "report_completeness": ctx.report_completeness,
                "capture_mode": ctx.mode,
                "usage_by_key": snapshot.usage_by_key,
                "unit_by_key": snapshot.unit_by_key,
                "usage_by_producer": snapshot.usage_by_producer,
                "unit_conflicts": snapshot.unit_conflicts,
            },
            timestamp=ctx.snapshot_at,
        )
        captured += 1
        if captured % CAPTURE_BATCH_SIZE == 0:
            ph_client.flush()
    if captured % CAPTURE_BATCH_SIZE:
        ph_client.flush()
    return captured


@activity.defn(name="gather-experimental-realtime-usage")
async def gather_experimental_realtime_usage(
    ctx: ExperimentalRealtimeUsageContext,
) -> GatherExperimentalRealtimeUsageResult:
    async with Heartbeater():
        query_started = time.monotonic()
        rows = await sync_to_async(get_canonical_usage_rows, thread_sensitive=False)(ctx)
        query_duration_ms = int((time.monotonic() - query_started) * 1000)
        snapshots = build_usage_snapshots(rows)
        capture_started = time.monotonic()
        organizations_captured = 0
        if ctx.mode != "dry_run":
            organizations_captured = await sync_to_async(capture_usage_snapshots, thread_sensitive=False)(
                snapshots, ctx, event_name_for_mode(ctx.mode)
            )
        capture_duration_ms = int((time.monotonic() - capture_started) * 1000)
        return GatherExperimentalRealtimeUsageResult(
            canonical_row_count=len(rows),
            organizations_found=len(snapshots),
            organizations_captured=organizations_captured,
            usage_key_count=len({usage_key for _, _, usage_key, _, _ in rows}),
            query_duration_ms=query_duration_ms,
            capture_duration_ms=capture_duration_ms,
        )


@workflow.defn(name="gather-experimental-realtime-usage")
class GatherExperimentalRealtimeUsageWorkflow(PostHogWorkflow):
    inputs_cls = GatherExperimentalRealtimeUsageInputs

    @workflow.run
    async def run(self, inputs: GatherExperimentalRealtimeUsageInputs) -> GatherExperimentalRealtimeUsageResult:
        if inputs.day_offset < 0:
            raise ApplicationError(f"day_offset must be >= 0, got {inputs.day_offset}", non_retryable=True)
        ctx = build_experimental_realtime_context(inputs, workflow.now())
        return await workflow.execute_activity(
            gather_experimental_realtime_usage,
            ctx,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30)),
        )
