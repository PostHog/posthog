"""Activity to update the SignalSourceConfig status after clustering completes."""

from dataclasses import dataclass

import structlog
import temporalio.activity
from asgiref.sync import sync_to_async

logger = structlog.get_logger(__name__)


@dataclass
class UpdateSourceConfigStatusInput:
    team_id: int
    status: str


@temporalio.activity.defn
async def update_source_config_status_activity(input: UpdateSourceConfigStatusInput) -> None:
    """Update the status field on the team's session analysis SignalSourceConfig."""
    from products.signals.backend.models import SignalSourceConfig

    def do_update():
        SignalSourceConfig.objects.filter(
            team_id=input.team_id,
            source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS,
        ).update(status=input.status)

    await sync_to_async(do_update, thread_sensitive=False)()
    logger.debug(
        "Updated source config status",
        team_id=input.team_id,
        status=input.status,
    )
