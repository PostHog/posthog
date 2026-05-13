"""Cancel an in-flight deployment.

Sends a cancellation signal to the Temporal workflow via the adapter. The
workflow's cancellation handler eventually POSTs `status=cancelled` back
to our internal transitions endpoint, which is what actually flips the
DB row. We don't write `cancelled` here ourselves — the workflow is
authoritative about its own state.
"""

from __future__ import annotations

from ..adapters import WorkflowAdapter, get_workflow_adapter
from ..models import Deployment


class DeploymentNotCancellable(Exception):
    """The deployment is already in a terminal state."""


def execute(*, deployment_id: str, team_id: int, workflow: WorkflowAdapter | None = None) -> Deployment:
    deployment = Deployment.objects.get(pk=deployment_id, team_id=team_id)
    if deployment.status not in Deployment.NON_TERMINAL_STATUSES:
        raise DeploymentNotCancellable(f"Deployment is already {deployment.status}.")

    if deployment.temporal_workflow_id:
        wf = workflow or get_workflow_adapter()
        wf.signal_cancel(workflow_id=deployment.temporal_workflow_id)
    # If we have no workflow_id (rare — the create_deployment flow failed
    # mid-dispatch), there's no worker to signal. Leave the row in its
    # current state and let the operator clean it up via the admin.
    return deployment
