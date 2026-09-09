from posthog.api.routing import RouterRegistry

from products.cdp.backend.api import hog_function, hog_function_template


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"hog_functions", hog_function.HogFunctionViewSet, "project_hog_functions", ["team_id"])
    routers.projects.register(
        r"hog_function_templates",
        hog_function_template.PublicHogFunctionTemplateViewSet,
        "project_hog_function_templates",
        ["project_id"],
    )
