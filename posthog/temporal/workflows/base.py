from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from posthog.batch_exports.service import update_batch_export_run_status, create_batch_export_run
from posthog.batch_exports.models import afetch_batch_export
from temporalio import activity
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.temporal.workflows.batch_exports import get_data_interval_from_workflow_inputs


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
class CreateBatchExportRunInputs:
    """Inputs to the create_export_run activity.

    Attributes:
        batch_export_id: The id of the BatchExport this BatchExportRun belongs to.
        data_interval_start: Start of this BatchExportRun's data interval.
        data_interval_end: End of this BatchExportRun's data interval.
    """

    batch_export_id: str
    data_interval_end: str


@activity.defn
async def create_export_run(inputs: CreateBatchExportRunInputs) -> str | None:
    """Activity that creates an BatchExportRun.

    Intended to be used in all export workflows, usually at the start, to create a model
    instance to represent them in our database.
    """
    activity.logger.info("Creating BatchExportRun model for export: %s", inputs.batch_export_id)

    batch_export = await afetch_batch_export(UUID(inputs.batch_export_id))
    if not batch_export:
        activity.logger.warn(f"BatchExport {inputs.batch_export_id} does not exist")
        return None

    datetime.fromisoformat(inputs.data_interval_end)
    (data_interval_start, data_interval_end) = get_data_interval_from_workflow_inputs(
        interval="hour", data_interval_end=datetime.fromisoformat(inputs.data_interval_end)
    )

    # 'sync_to_async' type hints are fixed in asgiref>=3.4.1
    # But one of our dependencies is pinned to asgiref==3.3.2.
    # Remove these comments once we upgrade.
    run = await sync_to_async(create_batch_export_run)(  # type: ignore
        batch_export_id=UUID(inputs.batch_export_id),
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
    )

    activity.logger.info(f"Created BatchExportRun {run.id}")

    return str(run.id)


@dataclass
class UpdateBatchExportRunStatusInputs:
    """Inputs to the update_export_run_status activity."""

    id: str
    status: str


@activity.defn
async def update_export_run_status(inputs: UpdateBatchExportRunStatusInputs):
    """Activity that updates the status of an BatchExportRun."""
    await sync_to_async(update_batch_export_run_status)(run_id=UUID(inputs.id), status=inputs.status)  # type: ignore
