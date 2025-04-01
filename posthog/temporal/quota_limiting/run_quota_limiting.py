import json
from temporalio import activity, workflow, common
from datetime import timedelta
import dataclasses
import structlog
import logging

from posthog.temporal.common.base import PostHogWorkflow
from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.heartbeat import Heartbeater
from asgiref.sync import sync_to_async


logger = structlog.get_logger()
logging.basicConfig(level=logging.INFO)


@dataclasses.dataclass
class RunQuotaLimitingInputs:
    pass


@dataclasses.dataclass
class RunQuotaLimitingAllOrgsInputs:
    pass


@activity.defn(name="run-quota-limiting-all-orgs")
async def run_quota_limiting_all_orgs(
    _inputs: RunQuotaLimitingAllOrgsInputs,
) -> None:
    async with Heartbeater():
        try:
            from ee.billing.quota_limiting import update_all_orgs_billing_quotas

            @sync_to_async
            def async_update_all_orgs_billing_quotas():
                update_all_orgs_billing_quotas()

            await async_update_all_orgs_billing_quotas()
        except ImportError:
            pass
        except Exception as e:
            capture_exception(e)
            raise


@workflow.defn(name="run-quota-limiting")
class RunQuotaLimitingWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> RunQuotaLimitingInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return RunQuotaLimitingInputs(**loaded)

    @workflow.run
    async def run(self, _inputs: RunQuotaLimitingInputs) -> None:
        try:
            await workflow.execute_activity(
                run_quota_limiting_all_orgs,
                RunQuotaLimitingAllOrgsInputs(),
                start_to_close_timeout=timedelta(minutes=20),
                retry_policy=common.RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(minutes=1),
                ),
                heartbeat_timeout=timedelta(minutes=1),
            )

        except Exception as e:
            capture_exception(e)
            raise
