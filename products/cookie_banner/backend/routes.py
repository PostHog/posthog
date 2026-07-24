from posthog.api.routing import RouterRegistry

from products.cookie_banner.backend.presentation.views import CookieBannerConfigViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"cookie_banner", CookieBannerConfigViewSet, "project_cookie_banner", ["team_id"])
