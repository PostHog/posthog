import asyncio
import dataclasses
import datetime as dt

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from ee.billing.quota_limiting import (
    QuotaLimitingCaches,
    QuotaResource,
    list_limited_team_attributes,
)
from posthog.batch_exports.models import BatchExportRun
from posthog.models.team.team import Team
from products.batch_exports.backend.temporal.batch_exports import (
    FinishBatchExportRunInputs,
    finish_batch_export_run,
)

LOGGER = structlog.get_logger(__name__)


@dataclasses.dataclass
class IsOverBillingLimitActivityInputs:
    team_id: int


@activity.defn
async def is_over_billing_limit_activity(inputs: IsOverBillingLimitActivityInputs) -> bool:
    """Check if team has exceeded billing limits.

    If so, the batch export should fail to run.
    """
    logger = LOGGER.bind(team_id=inputs.team_id)
    team: Team = await Team.objects.aget(id=inputs.team_id)

    limited_team_tokens_rows_synced = await asyncio.to_thread(
        list_limited_team_attributes, QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
    )

    if team.api_token in limited_team_tokens_rows_synced:
        logger.warning("Over billing limit")
        return True

    return False


class OverBillingLimitError(Exception):
    pass


async def ensure_batch_export_within_billing_limit(batch_export_id: str, run_id: str, team_id: int) -> None:
    """Ensures a batch export is within billing limit.

    This chooses to raise an exception to force callers to handle it, as the batch
    export should immediately return when raised.

    Raises:
        OverBillingLimitError: When over billing limit.
    """
    is_over_billing_limit = await workflow.execute_activity(
        is_over_billing_limit_activity,
        IsOverBillingLimitActivityInputs(team_id=team_id),
        start_to_close_timeout=dt.timedelta(minutes=5),
        retry_policy=RetryPolicy(
            initial_interval=dt.timedelta(seconds=5),
            maximum_interval=dt.timedelta(seconds=60),
            maximum_attempts=0,
        ),
    )

    if not is_over_billing_limit:
        return

    finish_inputs = FinishBatchExportRunInputs(
        id=run_id,
        batch_export_id=batch_export_id,
        status=BatchExportRun.Status.FAILED,
        team_id=team_id,
        latest_error="Over billing limit",
    )

    await workflow.execute_activity(
        finish_batch_export_run,
        finish_inputs,
        start_to_close_timeout=dt.timedelta(minutes=5),
        retry_policy=RetryPolicy(
            initial_interval=dt.timedelta(seconds=10),
            maximum_interval=dt.timedelta(seconds=60),
            maximum_attempts=0,
            non_retryable_error_types=["NotNullViolation", "IntegrityError"],
        ),
    )

    raise OverBillingLimitError()
