from uuid import UUID

from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit


@shared_task(ignore_result=True)
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

    try:
        for organization_id in organization_ids:
            result = stop_organization_background_work(
                UUID(organization_id),
                deactivated=organization_id in deactivated_ids,
                reason=reason,
                triggered_by=triggered_by,
            )
            if result is not None:
                ShutdownRuns.record(run_id, result)
    except Exception:
        ShutdownRuns.finish(run_id, crashed=True)
        raise
    ShutdownRuns.finish(run_id)
