"""CDC Temporal workflows.

CDCExtractionWorkflow: source-level scheduled workflow that reads all WAL changes
from the replication slot, groups them by table, and writes them through the
pipeline (S3BatchWriter → KafkaBatchProducer → Kafka consumer → DeltaLake).
"""

from __future__ import annotations

import json
import uuid
import typing
import datetime as dt
import dataclasses

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow


@dataclasses.dataclass
class CDCExtractionInput:
    team_id: int
    source_id: uuid.UUID

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "source_id": str(self.source_id),
        }


@workflow.defn(name="cdc-extraction")
class CDCExtractionWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> CDCExtractionInput:
        loaded = json.loads(inputs[0])
        return CDCExtractionInput(**loaded)

    @workflow.run
    async def run(self, inputs: CDCExtractionInput) -> None:
        from posthog.temporal.data_imports.cdc.activities import CDCExtractInput, cdc_extract_activity

        await workflow.execute_activity(
            cdc_extract_activity,
            CDCExtractInput(
                team_id=inputs.team_id,
                source_id=inputs.source_id,
            ),
            start_to_close_timeout=dt.timedelta(hours=2),
            heartbeat_timeout=dt.timedelta(minutes=10),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=30),
                maximum_interval=dt.timedelta(minutes=5),
                maximum_attempts=3,
            ),
        )


@workflow.defn(name="cdc-slot-cleanup")
class CDCSlotCleanupWorkflow(PostHogWorkflow):
    """Hourly sweep: clean up orphaned CDC slots and monitor WAL lag."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        return None

    @workflow.run
    async def run(self, inputs: None = None) -> None:
        from posthog.temporal.data_imports.cdc.activities import cleanup_orphan_slots_activity

        await workflow.execute_activity(
            cleanup_orphan_slots_activity,
            start_to_close_timeout=dt.timedelta(minutes=15),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=30),
                maximum_interval=dt.timedelta(seconds=300),
                maximum_attempts=2,
            ),
        )
