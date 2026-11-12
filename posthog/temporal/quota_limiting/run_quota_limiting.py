import json
import time
import logging
import dataclasses
from collections.abc import Callable, Sequence
from datetime import timedelta

import structlog
from temporalio import activity, common, workflow
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Organization
from posthog.sync import database_sync_to_async
from posthog.tasks.sync_billing import sync_organization_from_billing
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater

logger = structlog.get_logger()
logging.basicConfig(level=logging.INFO)

SYNC_ENDED_BILLING_PERIODS_PATCH_ID = "sync-ended-billing-periods-2026-11"
# One fixed ID keeps a single sync running, so the requests to billing never exceed one sync's rate.
SYNC_ENDED_BILLING_PERIODS_WORKFLOW_ID = "sync-ended-billing-periods"
# Keeps the activity result well under Temporal's payload limit when billing sends no statuses for days.
MAX_ENDED_PERIOD_ORGS_PER_RUN = 5_000
# The same rate as the `sync_from_billing` Celery task.
BILLING_SYNC_MIN_INTERVAL_S = 0.2
BILLING_SYNC_TIMEOUT = (5.0, 30.0)


@dataclasses.dataclass
class RunQuotaLimitingInputs:
    pass


@dataclasses.dataclass
class RunQuotaLimitingAllOrgsInputs:
    pass


@dataclasses.dataclass
class QuotaLimitingResult:
    duration_s: float = 0.0
    orgs_total: int = 0
    orgs_processed: int = 0
    orgs_limited: int = 0
    orgs_suspended: int = 0
    ended_period_org_ids: list[str] = dataclasses.field(default_factory=list)


@frozen
class SyncEndedBillingPeriodsInputs:
    organization_ids: list[str]


@frozen
class SyncEndedBillingPeriodsResult:
    synced: int
    failed: int


@activity.defn(name="run-quota-limiting-all-orgs")
async def run_quota_limiting_all_orgs(
    _inputs: RunQuotaLimitingAllOrgsInputs,
) -> QuotaLimitingResult:
    result = QuotaLimitingResult()
    async with Heartbeater() as heartbeater:
        try:
            from ee.billing.quota_limiting import update_all_orgs_billing_quotas

            def progress_callback(phase: str, progress: str, detail: str) -> None:
                heartbeater.details = (phase, progress, detail)

            @database_sync_to_async(thread_sensitive=True)
            def async_update_all_orgs_billing_quotas():
                return update_all_orgs_billing_quotas(progress_callback=progress_callback)

            run_result = await async_update_all_orgs_billing_quotas()
            result = QuotaLimitingResult(
                **run_result.stats,
                ended_period_org_ids=run_result.ended_period_org_ids[:MAX_ENDED_PERIOD_ORGS_PER_RUN],
            )
        except ImportError:
            pass
        except Exception as e:
            capture_exception(e)
            # Raise exception without large context to avoid "Failure exceeds size limit"
            raise Exception(f"Quota limiting failed: {type(e).__name__}: {str(e)[:200]}...")
    return result


def sync_organizations_from_billing(
    organization_ids: Sequence[str],
    *,
    min_interval_s: float = BILLING_SYNC_MIN_INTERVAL_S,
    on_progress: Callable[[int], None] | None = None,
) -> SyncEndedBillingPeriodsResult:
    synced = failed = 0
    for done, organization_id in enumerate(organization_ids, start=1):
        started = time.monotonic()
        try:
            sync_organization_from_billing(organization_id, timeout=BILLING_SYNC_TIMEOUT)
            synced += 1
        except Organization.DoesNotExist:
            pass
        except Exception:
            # The organization keeps its ended period, so the next quota run asks again.
            failed += 1
            logger.warning("sync_ended_billing_period_failed", organization_id=organization_id, exc_info=True)
        if on_progress:
            on_progress(done)
        time.sleep(max(0.0, min_interval_s - (time.monotonic() - started)))
    logger.info("sync_ended_billing_periods_done", synced=synced, failed=failed, requested=len(organization_ids))
    return SyncEndedBillingPeriodsResult(synced=synced, failed=failed)


@activity.defn(name="sync-ended-billing-periods")
async def sync_ended_billing_periods(inputs: SyncEndedBillingPeriodsInputs) -> SyncEndedBillingPeriodsResult:
    async with Heartbeater() as heartbeater:

        def on_progress(done: int) -> None:
            heartbeater.details = (done, len(inputs.organization_ids))

        # Thread-sensitive calls share one thread, and the next quota run must not wait behind these requests.
        @database_sync_to_async(thread_sensitive=False)
        def sync_all() -> SyncEndedBillingPeriodsResult:
            return sync_organizations_from_billing(inputs.organization_ids, on_progress=on_progress)

        return await sync_all()


@workflow.defn(name="sync-ended-billing-periods")
class SyncEndedBillingPeriodsWorkflow(PostHogWorkflow):
    inputs_cls = SyncEndedBillingPeriodsInputs

    @workflow.run
    async def run(self, inputs: SyncEndedBillingPeriodsInputs) -> SyncEndedBillingPeriodsResult:
        return await workflow.execute_activity(
            sync_ended_billing_periods,
            inputs,
            start_to_close_timeout=timedelta(hours=2),
            heartbeat_timeout=timedelta(minutes=2),
            # The next quota run finds every organization that a failed attempt left with an ended period.
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        )


@workflow.defn(name="run-quota-limiting")
class RunQuotaLimitingWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> RunQuotaLimitingInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return RunQuotaLimitingInputs(**loaded)

    @workflow.run
    async def run(self, _inputs: RunQuotaLimitingInputs) -> QuotaLimitingResult:
        try:
            result = await workflow.execute_activity(
                run_quota_limiting_all_orgs,
                RunQuotaLimitingAllOrgsInputs(),
                start_to_close_timeout=timedelta(hours=12),
                retry_policy=common.RetryPolicy(
                    maximum_attempts=1,
                ),
                heartbeat_timeout=timedelta(minutes=2),
            )

        except Exception as e:
            capture_exception(e)
            raise

        if workflow.patched(SYNC_ENDED_BILLING_PERIODS_PATCH_ID) and result.ended_period_org_ids:
            await self._start_billing_sync(result.ended_period_org_ids)
        return result

    async def _start_billing_sync(self, organization_ids: list[str]) -> None:
        # The run does not wait for billing, so a slow billing service cannot delay the next run.
        try:
            await workflow.start_child_workflow(
                SyncEndedBillingPeriodsWorkflow.run,
                SyncEndedBillingPeriodsInputs(organization_ids=organization_ids),
                id=SYNC_ENDED_BILLING_PERIODS_WORKFLOW_ID,
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
            )
        except WorkflowAlreadyStartedError:
            workflow.logger.info(
                "Billing sync for ended periods is still running", extra={"organizations": len(organization_ids)}
            )
