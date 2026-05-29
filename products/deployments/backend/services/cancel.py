"""Cancel an in-flight deployment.

Two paths:

1. Normal case: `temporal_workflow_id` is set. Send a cancel signal to
   Temporal via the adapter. The workflow's cancellation handler will
   eventually POST `status=cancelled` back to the internal transitions
   endpoint, which is what actually flips the DB row.
2. Orphan case: `temporal_workflow_id` is empty. This happens when
   `create_deployment` committed the row but `start_build` failed before
   persisting the handle. There is no worker to signal — flip the row
   to CANCELLED directly through `update_status` so the state machine
   stays the single source of truth.

Returns True if a signal was sent, False if the row was directly flipped.
The caller (viewset) uses this to surface an accurate response message.
"""

from __future__ import annotations

from ..adapters import WorkflowAdapter, get_workflow_adapter
from ..domain.status import Status
from ..models import Deployment


class DeploymentNotCancellable(Exception):
    """The deployment is already in a terminal state."""


def execute(*, deployment_id: str, team_id: int, workflow: WorkflowAdapter | None = None) -> bool:
    # Imported here to avoid a circular import with update_status, which
    # depends on this module's domain types transitively.
    from . import update_status

    deployment = Deployment.objects.get(pk=deployment_id, team_id=team_id)
    if deployment.status not in Deployment.NON_TERMINAL_STATUSES:
        raise DeploymentNotCancellable(f"Deployment is already {deployment.status}.")

    if deployment.temporal_workflow_id:
        wf = workflow or get_workflow_adapter()
        wf.signal_cancel(workflow_id=deployment.temporal_workflow_id)
        return True

    # Orphan: no workflow to signal. Drive the state machine ourselves so
    # the row doesn't sit in QUEUED forever.
    update_status.execute(
        update_status.UpdateStatusInput(
            deployment_id=str(deployment.pk),
            status=Status.CANCELLED,
        )
    )
    return False
