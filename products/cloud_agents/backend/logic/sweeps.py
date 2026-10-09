"""Stop the billed runs of a project that is over its usage limit."""

from __future__ import annotations

from typing import Final

import structlog

from products.tasks.backend.facade.cancellation import cancel_task_run
from products.tasks.backend.facade.cloud_agents import list_active_billable_cloud_agent_runs
from products.tasks.backend.facade.compute_quota import list_teams_over_cloud_agents_quota_with_active_runs

from .status import QUOTA_SWEEP_CANCEL_SOURCE

logger = structlog.get_logger(__name__)

USAGE_LIMIT_CANCEL_REASON: Final = "Stopped because the project reached its usage limit"
QUOTA_SWEEP_BATCH_SIZE: Final = 200


def stop_runs_over_quota(*, batch_size: int = QUOTA_SWEEP_BATCH_SIZE) -> int:
    """Cancel the active billed runs of every project that is over its limit. Returns how many it cancelled.

    One call asks Tasks to cancel `batch_size` runs at most. The next call continues, because a
    cancelled run is not active.
    """
    cancelled = 0
    attempts = 0
    for team_id in list_teams_over_cloud_agents_quota_with_active_runs():
        if attempts >= batch_size:
            break
        for active in list_active_billable_cloud_agent_runs(team_id=team_id, limit=batch_size - attempts):
            attempts += 1
            try:
                outcome, _ = cancel_task_run(
                    active.task_run_id,
                    active.task_id,
                    team_id,
                    reason=USAGE_LIMIT_CANCEL_REASON,
                    source=QUOTA_SWEEP_CANCEL_SOURCE,
                )
            except Exception:
                logger.exception(
                    "cloud_agents_quota_sweep_cancel_failed", team_id=team_id, task_run_id=str(active.task_run_id)
                )
                continue
            if outcome == "accepted":
                cancelled += 1
    return cancelled
