import uuid
from dataclasses import is_dataclass
from typing import Any

from django.conf import settings

from prometheus_client import Counter
from temporalio import activity
from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput, Interceptor

from posthog.models import organization_admission
from posthog.models.organization_admission import Admission
from posthog.sync import database_sync_to_async
from posthog.temporal.common.interceptor import ALL_TASK_QUEUES
from posthog.temporal.common.logger import get_write_only_logger

SHADOW_MODE = "shadow"

ADMISSION_CHECKS = Counter(
    "temporal_organization_admission_checks",
    "Activities checked against their organization's deactivation state, by the outcome of the check.",
    labelnames=["task_queue", "activity_type", "outcome"],
)

_SHADOW_OUTCOMES = {
    Admission.ADMITTED: "admitted",
    Admission.DEACTIVATED: "would_skip",
    Admission.UNRESOLVED: "unresolved",
}

logger = get_write_only_logger()


def _tenant_of(input: ExecuteActivityInput) -> tuple[int | None, uuid.UUID | str | None]:
    if not (len(input.args) == 1 and is_dataclass(input.args[0])):
        return None, None
    team_id = getattr(input.args[0], "team_id", None)
    organization_id = getattr(input.args[0], "organization_id", None)
    return (
        team_id if isinstance(team_id, int) and not isinstance(team_id, bool) and team_id > 0 else None,
        organization_id if isinstance(organization_id, uuid.UUID | str) else None,
    )


async def _shadow_outcome(input: ExecuteActivityInput) -> str:
    team_id, organization_id = _tenant_of(input)
    if team_id is None and organization_id is None:
        return _SHADOW_OUTCOMES[Admission.UNRESOLVED]
    admission = await database_sync_to_async(organization_admission.organization_deactivated)(
        team_id=team_id, organization_id=organization_id
    )
    return _SHADOW_OUTCOMES[admission]


async def _record_shadow_admission(input: ExecuteActivityInput) -> None:
    try:
        outcome = await _shadow_outcome(input)
    except Exception as error:
        outcome = "error"
        await logger.awarning("organization_admission_check_failed", exc_info=error)
    try:
        info = activity.info()
        ADMISSION_CHECKS.labels(task_queue=info.task_queue, activity_type=info.activity_type, outcome=outcome).inc()
    except Exception as error:
        await logger.awarning("organization_admission_metric_failed", exc_info=error)


class _OrganizationAdmissionActivityInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        if settings.TEMPORAL_ORGANIZATION_ADMISSION_MODE == SHADOW_MODE:
            await _record_shadow_admission(input)
        return await super().execute_activity(input)


class OrganizationAdmissionInterceptor(Interceptor):
    task_queue = ALL_TASK_QUEUES

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _OrganizationAdmissionActivityInterceptor(super().intercept_activity(next))
