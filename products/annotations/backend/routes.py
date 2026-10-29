from posthog.api.routing import RouterRegistry

from products.annotations.backend.api import annotation
from products.annotations.backend.presentation import views as change_feed_views


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"annotations", annotation.AnnotationsViewSet, "project_annotations", ["project_id"])
    routers.projects.register(
        r"change_feed", change_feed_views.ChangeFeedViewSet, "project_change_feed", ["project_id"]
    )
