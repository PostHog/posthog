from __future__ import annotations

import json
import time

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater

from products.customer_analytics.backend.facade.temporal_contracts import AccountPropertySyncInput

with workflow.unsafe.imports_passed_through():
    from datetime import timedelta

    import structlog
    from prometheus_client import Counter, Histogram

    from products.customer_analytics.backend.logic.account_property_sync import (
        AccountPropertySourceValueError,
        AccountPropertySyncSegment,
        run_account_property_segment_sync,
    )
    from products.warehouse_sources.backend.facade.hooks import saved_query_binding

logger = structlog.get_logger(__name__)

ACCOUNT_PROPERTY_SYNC_WORKFLOW_NAME = "sync-warehouse-account-properties"

ACCOUNT_PROPERTY_SYNC_TOTAL = Counter(
    "warehouse_account_property_sync_total",
    "Account-property sync activity attempts by segment and outcome",
    labelnames=["team_id", "segment", "outcome"],
)

ACCOUNT_PROPERTY_SYNC_DURATION_SECONDS = Histogram(
    "warehouse_account_property_sync_duration_seconds",
    "Duration of one account-property segment sync",
    labelnames=["segment"],
    buckets=(0.5, 1.0, 2.5, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0),
)


@activity.defn
async def sync_warehouse_account_properties_activity(input: AccountPropertySyncInput) -> dict[str, int]:
    segment = AccountPropertySyncSegment(input.segment)
    log = logger.bind(
        team_id=input.team_id,
        saved_query_id=input.saved_query_id,
        job_id=input.job_id,
        segment=segment.value,
    )
    started = time.monotonic()
    try:
        async with Heartbeater():
            result = await run_account_property_segment_sync(
                team_id=input.team_id,
                binding=saved_query_binding(input.saved_query_id),
                job_id=input.job_id,
                segment=segment,
            )
    except AccountPropertySourceValueError as error:
        ACCOUNT_PROPERTY_SYNC_TOTAL.labels(team_id=str(input.team_id), segment=segment.value, outcome="failed").inc()
        log.warning("Account-property segment sync rejected invalid source values", error=str(error))
        raise ApplicationError(str(error), non_retryable=True) from error
    except Exception as error:
        ACCOUNT_PROPERTY_SYNC_TOTAL.labels(team_id=str(input.team_id), segment=segment.value, outcome="failed").inc()
        log.exception("Account-property segment sync failed")
        capture_exception(error)
        raise

    ACCOUNT_PROPERTY_SYNC_TOTAL.labels(team_id=str(input.team_id), segment=segment.value, outcome="completed").inc()
    ACCOUNT_PROPERTY_SYNC_DURATION_SECONDS.labels(segment=segment.value).observe(time.monotonic() - started)
    log.info("Account-property segment sync completed", **result)
    return result


@workflow.defn(name=ACCOUNT_PROPERTY_SYNC_WORKFLOW_NAME)
class SyncWarehouseAccountPropertiesWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> AccountPropertySyncInput:
        return AccountPropertySyncInput(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, input: AccountPropertySyncInput) -> None:
        await workflow.execute_activity(
            sync_warehouse_account_properties_activity,
            input,
            start_to_close_timeout=timedelta(hours=6),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=30)),
        )


ACCOUNT_PROPERTY_SYNC_WORKFLOWS = [SyncWarehouseAccountPropertiesWorkflow]
ACCOUNT_PROPERTY_SYNC_ACTIVITIES = [sync_warehouse_account_properties_activity]
