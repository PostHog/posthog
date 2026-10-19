from posthog.api.routing import RouterRegistry

from products.aeo.backend.presentation.views import AEOPromptViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"aeo_prompts", AEOPromptViewSet, "project_aeo_prompts", ["team_id"])
