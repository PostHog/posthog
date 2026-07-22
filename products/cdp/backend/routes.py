from posthog.api.routing import RouterRegistry

from products.cdp.backend.api import hog_function, hog_function_template, plugin, plugin_log_entry


def register_routes(routers: RouterRegistry) -> None:
    routers.root.register(r"plugin_config", plugin.LegacyPluginConfigViewSet, "legacy_plugin_configs")
    legacy_project_plugins_configs_router, environment_plugins_configs_router = routers.register_legacy_dual_route(
        r"plugin_configs", plugin.PluginConfigViewSet, "environment_plugin_configs", ["team_id"]
    )
    environment_plugins_configs_router.register(
        r"logs",
        plugin_log_entry.PluginLogEntryViewSet,
        "environment_plugin_config_logs",
        ["team_id", "plugin_config_id"],
    )
    legacy_project_plugins_configs_router.register(
        r"logs", plugin_log_entry.PluginLogEntryViewSet, "project_plugin_config_logs", ["team_id", "plugin_config_id"]
    )
    routers.register_legacy_dual_route(
        r"pipeline_transformation_configs",
        plugin.PipelineTransformationsConfigsViewSet,
        "environment_pipeline_transformation_configs",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"pipeline_destination_configs",
        plugin.PipelineDestinationsConfigsViewSet,
        "environment_pipeline_destination_configs",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"pipeline_frontend_apps_configs",
        plugin.PipelineFrontendAppsConfigsViewSet,
        "environment_pipeline_frontend_apps_configs",
        ["team_id"],
    )
    routers.register_legacy_dual_route(
        r"pipeline_import_apps_configs",
        plugin.PipelineImportAppsConfigsViewSet,
        "environment_pipeline_import_apps_configs",
        ["team_id"],
    )
    routers.organizations.register(r"plugins", plugin.PluginViewSet, "organization_plugins", ["organization_id"])
    routers.organizations.register(
        r"pipeline_transformations",
        plugin.PipelineTransformationsViewSet,
        "organization_pipeline_transformations",
        ["organization_id"],
    )
    routers.organizations.register(
        r"pipeline_destinations",
        plugin.PipelineDestinationsViewSet,
        "organization_pipeline_destinations",
        ["organization_id"],
    )
    routers.organizations.register(
        r"pipeline_frontend_apps",
        plugin.PipelineFrontendAppsViewSet,
        "organization_pipeline_frontend_apps",
        ["organization_id"],
    )
    routers.organizations.register(
        r"pipeline_import_apps",
        plugin.PipelineImportAppsViewSet,
        "organization_pipeline_import_apps",
        ["organization_id"],
    )
    routers.register_legacy_dual_route(
        r"hog_functions", hog_function.HogFunctionViewSet, "environment_hog_functions", ["team_id"]
    )
    routers.projects.register(
        r"hog_function_templates",
        hog_function_template.PublicHogFunctionTemplateViewSet,
        "project_hog_function_templates",
        ["project_id"],
    )
