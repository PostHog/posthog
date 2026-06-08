from posthog.api.routing import RouterRegistry

from products.annotations.backend.api import annotation


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"annotations", annotation.AnnotationsViewSet, "project_annotations", ["project_id"])
