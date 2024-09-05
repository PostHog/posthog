import dataclasses
from temporalio import activity

from asgiref.sync import sync_to_async

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, list_limited_team_attributes
from posthog.models.team.team import Team
from posthog.temporal.common.logger import bind_temporal_worker_logger
from posthog.warehouse.external_data_source.jobs import aupdate_external_job_status
from posthog.warehouse.models.external_data_job import ExternalDataJob


@dataclasses.dataclass
class CheckBillingLimitsActivityInputs:
    team_id: int
    job_id: str


@activity.defn
async def check_billing_limits_activity(inputs: CheckBillingLimitsActivityInputs) -> bool:
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)

    team: Team = await sync_to_async(Team.objects.get)(id=inputs.team_id)

    limited_team_tokens_rows_synced = list_limited_team_attributes(
        QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
    )

    if team.api_token in limited_team_tokens_rows_synced:
        logger.info("Billing limits hit. Canceling sync")

        await aupdate_external_job_status(
            job_id=inputs.job_id,
            status=ExternalDataJob.Status.CANCELLED,
            latest_error=None,
            team_id=inputs.team_id,
        )

        return True

    return False
