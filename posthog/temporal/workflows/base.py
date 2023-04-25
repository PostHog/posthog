from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.models.export import ExportRun


class PostHogWorkflow(ABC):
    """Base class for Temporal Workflows that can be executed in PostHog."""

    @classmethod
    def get_name(cls) -> str:
        """Get this workflow's name."""
        return getattr(cls, "__temporal_workflow_definition").name

    @classmethod
    def is_named(cls, name: str) -> bool:
        """Check if this workflow's name matches name.

        All temporal workflows have the __temporal_workflow_definition attribute
        injected into them by the defn decorator. We use it to access the name and
        avoid having to define it twice. If this changes in the future, we can
        update this method instead of changing every single workflow.
        """
        return cls.get_name() == name

    @staticmethod
    @abstractmethod
    def parse_inputs(inputs: list[str]) -> Any:
        """Parse inputs from the management command CLI.

        If a workflow is to be executed via the CLI it must know how to parse its
        own inputs.
        """
        return NotImplemented


@dataclass
class CreateExportRunInputs:
    """Inputs to the create_export_run activity.

    Attributes:
        team_id: The id of the team the ExportRun belongs to.
        destination_id: The id of the destination the ExportRun is targetting.
        schedule_id: If this ExportRun was triggered by a schedule, it's id, otherwise None.
        data_interval_start: Start of this ExportRun's data interval.
        data_interval_end: End of this ExportRun's data interval.
    """

    team_id: int
    destination_id: str
    schedule_id: str | None
    data_interval_start: str
    data_interval_end: str


@activity.defn
async def create_export_run(inputs: CreateExportRunInputs) -> str:
    """Activity that creates an ExportRun.

    Intended to be used in all export workflows, usually at the start, to create a model
    instance to represent them in our database.
    """
    activity.logger.info("Creating ExportRun model instance.")

    # 'sync_to_async' type hints are fixed in asgiref>=3.4.1
    # But one of our dependencies is pinned to asgiref==3.3.2.
    # Remove these comments once we upgrade.
    run = await sync_to_async(ExportRun.objects.create)(  # type: ignore
        team_id=inputs.team_id,
        destination_id=UUID(inputs.destination_id),
        schedule_id=UUID(inputs.schedule_id) if inputs.schedule_id else None,
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
    )

    activity.logger.info(
        f"Creating ExportRun {run.id} targetting destination {run.destination.id} in team {run.team.id}."
    )

    return str(run.id)


@dataclass
class UpdateExportRunStatusInputs:
    """Inputs to the update_export_run_status activity."""

    run_id: str
    status: str


@activity.defn
async def update_export_run_status(inputs: UpdateExportRunStatusInputs):
    """Activity that updates the status of an ExportRun."""
    update_run_status = sync_to_async(ExportRun.objects.update_status)
    await update_run_status(export_run_id=UUID(inputs.run_id), status=inputs.status)  # type: ignore
