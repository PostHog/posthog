from posthog.api.routing import RouterRegistry

from products.annotations.backend.api import annotation, change_feed


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"annotations", annotation.AnnotationsViewSet, "project_annotations", ["project_id"])
    routers.projects.register(r"change_feed", change_feed.ChangeFeedViewSet, "project_change_feed", ["project_id"])
