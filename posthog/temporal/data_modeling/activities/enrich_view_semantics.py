import dataclasses
from typing import Any

from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater
from posthog.temporal.common.logger import get_write_only_logger

from products.data_modeling.backend.facade.api import enrich_view_semantics_sync

# Write-only (no Kafka `log_entries`): internal background activity, not a user-facing sync. The temporal
# worker's global structlog config still merges workflow_id/run_id/attempt/task_queue onto every line.
logger = get_write_only_logger(__name__)


@dataclasses.dataclass
class EnrichViewSemanticsInputs:
    team_id: int
    saved_query_id: str

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"team_id": self.team_id, "saved_query_id": self.saved_query_id}


@activity.defn
async def enrich_view_semantics_activity(inputs: EnrichViewSemanticsInputs) -> dict[str, Any]:
    """Activity wrapper. Heartbeats and runs the (sync) view enrichment off the event loop."""
    async with Heartbeater():
        try:
            return await database_sync_to_async(enrich_view_semantics_sync, thread_sensitive=False)(
                inputs.team_id, inputs.saved_query_id
            )
        except Exception as e:
            # Surface unexpected failures (DB errors, etc.) to error tracking and structured logs — keyed
            # by saved_query_id/team_id — then re-raise so Temporal retries.
            capture_exception(e)
            logger.exception(
                "view_enrichment.activity_failed",
                team_id=inputs.team_id,
                saved_query_id=inputs.saved_query_id,
                error=str(e),
            )
            raise
