from posthog.api.routing import RouterRegistry

from products.aeo.backend.presentation.views import AEOBrandViewSet, AEOPromptViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"aeo_prompts", AEOPromptViewSet, "project_aeo_prompts", ["team_id"])
    routers.projects.register(r"aeo_brands", AEOBrandViewSet, "project_aeo_brands", ["team_id"])
