from posthog.api.routing import RouterRegistry

from products.cookie_banner.backend.presentation.views import CookieBannerConfigViewSet


def register_routes(routers: RouterRegistry) -> None:
    # project_id (not team_id): the banner is project-wide — writes canonicalize to the
    # project's root team via RootTeamMixin, so reads must be project-scoped to match
    routers.projects.register(r"cookie_banner", CookieBannerConfigViewSet, "project_cookie_banner", ["project_id"])
