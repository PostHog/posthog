"""Deletes the platform's alerts on a deleted insight, off the request that deleted it: the ones that
never had an insight row, and the copies whose row went with the insight.

The platform's delete resolves each alert's open incidents before it removes the destinations, so it
can call slow providers. A workflow runs it with retries. Kept out of the workflow modules, which
Temporal loads into its sandbox, because this connects a client.
"""

import hashlib
from collections.abc import Collection, Mapping, Sequence
from uuid import UUID

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync
from temporalio.common import WorkflowIDConflictPolicy

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.client import async_connect

from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts_platform.backend.facade.api import (
    delete_owned_configuration,
    owned_configuration_ids_without_source_rows,
)
from products.alerts_platform.backend.facade.contracts import SourceKind

logger = structlog.get_logger(__name__)

NATIVE_CLEANUP_WORKFLOW = "insight-alert-native-cleanup"


@frozen
class NativeCleanupInputs:
    team_id: int
    insight_ids: tuple[int, ...]


def native_alert_ids(inputs: NativeCleanupInputs) -> list[str]:
    return [
        str(configuration_id)
        for configuration_id in owned_configuration_ids_without_source_rows(
            team_id=inputs.team_id,
            source_kind=SourceKind.INSIGHT,
            source_config_key="insight_id",
            values=inputs.insight_ids,
            existing_source_ids=_existing_alert_ids,
        )
    ]


def delete_native_alert(team_id: int, configuration_id: str) -> None:
    """Raises on failure, so a retry deletes it. An alert already gone is not a failure."""
    delete_owned_configuration(team_id=team_id, configuration_id=UUID(configuration_id))


def _existing_alert_ids(alert_ids: Collection[UUID]) -> set[UUID]:
    # The ids come from the team's own copies.
    # nosemgrep: idor-lookup-without-team
    return set(AlertConfiguration.objects.filter(id__in=list(alert_ids)).values_list("id", flat=True))


def start_native_cleanup(insights_by_team: Mapping[int, Sequence[int]]) -> None:
    """Starts one cleanup workflow per team. Deletes inline when Temporal cannot be reached, because
    nothing else would delete these alerts."""
    for team_id, insight_ids in insights_by_team.items():
        inputs = NativeCleanupInputs(team_id=team_id, insight_ids=tuple(sorted(set(insight_ids))))
        try:
            async_to_sync(_start)(inputs)
        except Exception as error:
            capture_exception(error, {"team_id": team_id})
            delete_inline(inputs)


def delete_inline(inputs: NativeCleanupInputs) -> None:
    for configuration_id in native_alert_ids(inputs):
        try:
            delete_native_alert(inputs.team_id, configuration_id)
        except Exception:
            logger.exception(
                "Failed to delete an insight alert left on a deleted insight", configuration_id=configuration_id
            )


def cleanup_workflow_id(inputs: NativeCleanupInputs) -> str:
    # The same deletion started twice, such as by a retried request, runs once.
    digest = hashlib.sha256(",".join(map(str, inputs.insight_ids)).encode()).hexdigest()[:16]
    return f"{NATIVE_CLEANUP_WORKFLOW}-{inputs.team_id}-{digest}"


async def _start(inputs: NativeCleanupInputs) -> None:
    client = await async_connect()
    await client.start_workflow(
        NATIVE_CLEANUP_WORKFLOW,
        inputs,
        id=cleanup_workflow_id(inputs),
        task_queue=settings.ALERTS_PLATFORM_EVALUATION_TASK_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
