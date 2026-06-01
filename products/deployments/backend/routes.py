from posthog.api.routing import RouterRegistry

from products.deployments.backend.api import DeploymentProjectViewSet, DeploymentViewSet


def register_routes(routers: RouterRegistry) -> None:
    # DeploymentProject is the top-level entity; Deployment nests under it:
    # /api/projects/{team_id}/deployment_projects/{deployment_project_id}/deployments/...
    project_deployment_projects_router = routers.projects.register(
        r"deployment_projects",
        DeploymentProjectViewSet,
        "project_deployment_projects",
        ["project_id"],
    )
    project_deployment_projects_router.register(
        r"deployments",
        DeploymentViewSet,
        "project_deployment_projects_deployments",
        ["project_id", "deployment_project_id"],
    )
