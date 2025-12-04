import uuid
import typing
import dataclasses

import posthoganalytics
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.logger import get_logger
from posthog.temporal.utils import DuckLakeCopyWorkflowGateInputs

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class DuckLakeCopyDataImportsModelInput:
    """Metadata describing a data imports schema to copy into DuckLake."""

    schema_id: uuid.UUID
    schema_name: str
    source_type: str
    normalized_name: str
    table_uri: str
    job_id: str
    team_id: int


@dataclasses.dataclass
class DataImportsDuckLakeCopyInputs:
    """Workflow inputs passed to DuckLakeCopyDataImportsWorkflow."""

    team_id: int
    job_id: str
    models: list[DuckLakeCopyDataImportsModelInput]

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "job_id": self.job_id,
            "schema_ids": [str(model.schema_id) for model in self.models],
            "schema_names": [model.schema_name for model in self.models],
            "source_types": [model.source_type for model in self.models],
        }


@activity.defn
async def ducklake_copy_data_imports_gate_activity(inputs: DuckLakeCopyWorkflowGateInputs) -> bool:
    """Evaluate whether the DuckLake data imports copy workflow should run for a team."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    try:
        team = await database_sync_to_async(Team.objects.only("uuid", "organization_id").get)(id=inputs.team_id)
    except Team.DoesNotExist:
        await logger.aerror("Team does not exist when evaluating DuckLake data imports gate")
        return False

    try:
        return posthoganalytics.feature_enabled(
            "ducklake-copy-data-imports",
            str(team.uuid),
            groups={
                "organization": str(team.organization_id),
                "project": str(team.id),
            },
            group_properties={
                "organization": {
                    "id": str(team.organization_id),
                },
                "project": {
                    "id": str(team.id),
                },
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception as error:
        await logger.awarning(
            "Failed to evaluate DuckLake data imports feature flag",
            error=str(error),
        )
        capture_exception(error)
        return False
