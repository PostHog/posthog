import typing
import dataclasses
from datetime import UTC, datetime, timedelta

from django.db import close_old_connections

from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.models.team.team import Team
from posthog.temporal.common.logger import get_logger
from posthog.temporal.data_imports.external_data_job import ExternalDataJob, ExternalDataSource

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, list_limited_team_attributes

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
def check_billing_limits_activity(inputs: CheckBillingLimitsActivityInputs) -> bool:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()
    close_old_connections()

    job = ExternalDataJob.objects.get(id=inputs.job_id)
    source: ExternalDataSource = job.pipeline

    if source.created_at >= datetime.now() - timedelta(days=7):
        logger.info(
            f"Skipping billing limits check for newly created data source for 7-days free rows. source.created_at = {source.created_at}"
        )
        return False

    if datetime.now() >= dwh_pricing_free_period_start and datetime.now() <= dwh_pricing_free_period_end:
        logger.info(
            f"Skipping billing limits check for data synced during free period from {dwh_pricing_free_period_start} to {dwh_pricing_free_period_end}."
        )
        return False

    team: Team = Team.objects.get(id=inputs.team_id)

    limited_team_tokens_rows_synced = list_limited_team_attributes(
        QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
    )

    if team.api_token in limited_team_tokens_rows_synced:
        logger.info("Billing limits hit. Canceling sync")
        return True

    return False
