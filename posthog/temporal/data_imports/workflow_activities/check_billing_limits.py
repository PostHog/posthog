import typing
import dataclasses
from datetime import UTC, datetime, timedelta

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.models.team.team import Team
from posthog.settings.base_variables import TEST
from posthog.sync import database_sync_to_async
from posthog.temporal.common.logger import get_logger

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CheckBillingLimitsActivityInputs:
    team_id: int
    job_id: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "job_id": self.job_id,
        }


# To be removed after 2025-11-06
dwh_pricing_free_period_start = datetime(2025, 10, 29, 0, 0, 0, tzinfo=UTC)
dwh_pricing_free_period_end = datetime(2025, 11, 6, 0, 0, 0, tzinfo=UTC)


@activity.defn
async def check_billing_limits_activity(inputs: CheckBillingLimitsActivityInputs) -> bool:
    from posthog.temporal.data_imports.external_data_job import ExternalDataJob, ExternalDataSource

    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    @database_sync_to_async
    def _get_source_created_at() -> datetime:
        job = ExternalDataJob.objects.get(id=inputs.job_id)
        source: ExternalDataSource = job.pipeline
        return source.created_at

    source_created_at = await _get_source_created_at()

    if source_created_at >= datetime.now(UTC) - timedelta(days=7):
        await logger.ainfo(
            f"Skipping billing limits check for newly created data source for 7-days free rows. source.created_at = {source_created_at}"
        )
        return False

    if (
        not TEST
        and datetime.now(UTC) >= dwh_pricing_free_period_start
        and datetime.now(UTC) <= dwh_pricing_free_period_end
    ):
        await logger.ainfo(
            f"Skipping billing limits check for data synced during free period from {dwh_pricing_free_period_start} to {dwh_pricing_free_period_end}."
        )
        return False

    @database_sync_to_async
    def _check_team_limited() -> bool:
        team: Team = Team.objects.only("api_token").get(id=inputs.team_id)
        return is_team_limited(team.api_token, QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)

    if await _check_team_limited():
        await logger.ainfo("Billing limits hit. Canceling sync")
        return True

    return False
