import uuid
import asyncio
import contextlib
from dataclasses import is_dataclass
from enum import StrEnum
from typing import Any

from django.conf import settings

from prometheus_client import Counter
from pydantic import BaseModel
from temporalio import activity
from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput, Interceptor

from posthog.models import organization_admission
from posthog.models.organization_admission import Admission, AdmissionSnapshotMissing, OrganizationAdmission
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.interceptor import ALL_TASK_QUEUES
from posthog.temporal.common.logger import get_write_only_logger


class AdmissionMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"


ADMISSION_CHECKS = Counter(
    "temporal_organization_admission_checks",
    "Activities checked against their organization's deactivation state, by the outcome of the check.",
    labelnames=["task_queue", "activity_type", "outcome"],
)

ADMISSION_REFRESHES = Counter(
    "temporal_organization_admission_refreshes",
    "Background reloads of the set of deactivated organizations and their teams, by outcome.",
    labelnames=["outcome"],
)

_SHADOW_OUTCOMES = {
    Admission.ADMITTED: "admitted",
    Admission.DEACTIVATED: "would_skip",
    Admission.UNRESOLVED: "unresolved",
}

logger = get_write_only_logger()

_refresh: asyncio.Task[None] | None = None


def _tenant_of(input: ExecuteActivityInput) -> tuple[int | None, uuid.UUID | str | None]:
    if not (len(input.args) == 1 and (is_dataclass(input.args[0]) or isinstance(input.args[0], BaseModel))):
        return None, None
    team_id = getattr(input.args[0], "team_id", None)
    organization_id = getattr(input.args[0], "organization_id", None)
    return (
        team_id if isinstance(team_id, int) and not isinstance(team_id, bool) and team_id > 0 else None,
        organization_id if isinstance(organization_id, uuid.UUID | str) else None,
    )


def _record_refresh(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    with contextlib.suppress(Exception):
        ADMISSION_REFRESHES.labels(outcome="failed" if error else "succeeded").inc()
        if error:
            logger.warning("organization_admission_refresh_failed", exc_info=error)


def _start_refresh(admission: OrganizationAdmission) -> None:
    global _refresh
    loop = asyncio.get_running_loop()
    if _refresh is not None and not _refresh.done() and _refresh.get_loop() is loop:
        return
    if not admission.is_stale():
        return
    _refresh = loop.create_task(database_sync_to_async_pool(admission.refresh_if_stale)())
    _refresh.add_done_callback(_record_refresh)


def _shadow_outcome(input: ExecuteActivityInput) -> str:
    team_id, organization_id = _tenant_of(input)
    if team_id is None and organization_id is None:
        return _SHADOW_OUTCOMES[Admission.UNRESOLVED]
    admission = organization_admission.ORGANIZATION_ADMISSION
    _start_refresh(admission)
    try:
        return _SHADOW_OUTCOMES[admission.check_cached(team_id=team_id, organization_id=organization_id)]
    except AdmissionSnapshotMissing:
        return "unavailable"


def _record_shadow_admission(input: ExecuteActivityInput) -> None:
    try:
        outcome = _shadow_outcome(input)
    except Exception as error:
        outcome = "error"
        with contextlib.suppress(Exception):
            logger.warning("organization_admission_check_failed", exc_info=error)
    with contextlib.suppress(Exception):
        info = activity.info()
        ADMISSION_CHECKS.labels(task_queue=info.task_queue, activity_type=info.activity_type, outcome=outcome).inc()


class _OrganizationAdmissionActivityInterceptor(ActivityInboundInterceptor):
    def __init__(self, next: ActivityInboundInterceptor, mode: AdmissionMode) -> None:
        super().__init__(next)
        self._mode = mode

    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        if self._mode is AdmissionMode.SHADOW:
            _record_shadow_admission(input)
        return await super().execute_activity(input)


class OrganizationAdmissionInterceptor(Interceptor):
    task_queue = ALL_TASK_QUEUES

    def __init__(self) -> None:
        self._mode = AdmissionMode(settings.TEMPORAL_ORGANIZATION_ADMISSION_MODE)

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _OrganizationAdmissionActivityInterceptor(super().intercept_activity(next), self._mode)
