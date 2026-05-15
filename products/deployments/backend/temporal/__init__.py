"""Temporal workflows + activities for the Deployments product.

The `start_temporal_worker` management command imports `WORKFLOWS` and
`ACTIVITIES` from here and registers them on the `deployments-task-queue`.
"""

from .activities import (
    build_site,
    clone_repo,
    initialize_build,
    install_dependencies,
    mark_failed,
    mark_ready,
    start_building,
    upload_artifacts,
)
from .build_workflow import DeploymentBuildWorkflow

WORKFLOWS = [DeploymentBuildWorkflow]

ACTIVITIES = [
    initialize_build,
    clone_repo,
    install_dependencies,
    start_building,
    build_site,
    upload_artifacts,
    mark_ready,
    mark_failed,
]

__all__ = ["ACTIVITIES", "WORKFLOWS", "DeploymentBuildWorkflow"]
