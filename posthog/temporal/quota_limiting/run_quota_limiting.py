import json
import logging
import dataclasses
from datetime import timedelta

import structlog
from temporalio import activity, common, workflow

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import Heartbeater

logger = structlog.get_logger()
logging.basicConfig(level=logging.INFO)


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

            _limited, _suspended, stats = await async_update_all_orgs_billing_quotas()
            result = QuotaLimitingResult(**stats)
        except ImportError:
            pass
        except Exception as e:
            capture_exception(e)
            # Raise exception without large context to avoid "Failure exceeds size limit"
            raise Exception(f"Quota limiting failed: {type(e).__name__}: {str(e)[:200]}...")
    return result


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
            return await workflow.execute_activity(
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
