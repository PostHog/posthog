from posthog.api.routing import RouterRegistry

from products.cloud_agents.backend.presentation import views

# (URL prefix, viewset, basename). Add the next resource as one more row.
PROJECT_ROUTES = [
    (r"cloud_agents/runs", views.CloudAgentRunViewSet, "project_cloud_agents_runs"),
    # The actions supply the last segment: cloud_agents/catalog, cloud_agents/estimate, cloud_agents/usage.
    (r"cloud_agents", views.CloudAgentsCatalogViewSet, "project_cloud_agents_catalog"),
    (r"cloud_agents/presets", views.CloudAgentPresetViewSet, "project_cloud_agents_presets"),
    # The viewset's `settings` action supplies the last segment: cloud_agents/settings.
    (r"cloud_agents", views.CloudAgentSettingsViewSet, "project_cloud_agents_settings"),
]


def register_routes(routers: RouterRegistry) -> None:
    for prefix, viewset, basename in PROJECT_ROUTES:
        routers.projects.register(prefix, viewset, basename, ["team_id"])
