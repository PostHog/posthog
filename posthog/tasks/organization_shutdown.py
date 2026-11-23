from collections.abc import Callable
from functools import partial
from uuid import UUID

import structlog
from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

logger = structlog.get_logger(__name__)


# Acknowledged late, so a worker that dies mid-run hands the task to another one. A second pass stops only what still
# runs, and the run page merges its results into the first pass's.
@shared_task(ignore_result=True, acks_late=True, reject_on_worker_lost=True)
@skip_team_scope_audit
def stop_organizations_background_work(
    run_id: str, organization_ids: list[str], deactivated_ids: list[str], reason: str, triggered_by: str
) -> None:
    """Stops the background work of the organizations of a bulk shutdown, one at a time, and records each result
    where the console's run page reads it."""
    # Deferred: the console module pulls in every product facade it stops work through.
    from posthog.admin.console.organization_shutdown import (  # noqa: PLC0415
        ShutdownRuns,
        stop_organization_background_work,
    )

    def progress(write: Callable[[], None]) -> None:
        # The audit log keeps every stopped ID, so a progress write that fails must not stop the shutdown.
        try:
            write()
        except Exception:
            logger.warning("organization_shutdown_progress_not_saved", run_id=run_id, exc_info=True)

    try:
        for organization_id in organization_ids:
            result = stop_organization_background_work(
                UUID(organization_id),
                deactivated=organization_id in deactivated_ids,
                reason=reason,
                triggered_by=triggered_by,
            )
            if result is not None:
                progress(partial(ShutdownRuns.record, run_id, result))
    except Exception:
        progress(partial(ShutdownRuns.finish, run_id, crashed=True))
        raise
    progress(partial(ShutdownRuns.finish, run_id))
