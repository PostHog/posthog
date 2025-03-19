import dataclasses
import typing

from django.db import close_old_connections
from temporalio import activity

from ee.billing.quota_limiting import (
    QuotaLimitingCaches,
    QuotaResource,
    list_limited_team_attributes,
)
from posthog.models.team.team import Team
from posthog.temporal.common.logger import bind_temporal_worker_logger_sync


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


@activity.defn
def check_billing_limits_activity(inputs: CheckBillingLimitsActivityInputs) -> bool:
    logger = bind_temporal_worker_logger_sync(team_id=inputs.team_id)
    close_old_connections()

    team: Team = Team.objects.get(id=inputs.team_id)

    limited_team_tokens_rows_synced = list_limited_team_attributes(
        QuotaResource.ROWS_SYNCED, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY
    )

    if team.api_token in limited_team_tokens_rows_synced:
        logger.info("Billing limits hit. Canceling sync")
        return True

    return False
