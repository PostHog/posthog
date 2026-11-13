"""A route that accepts OAuth access tokens accepts ID-JAG access tokens too.

An MCP client signed in through enterprise-managed authorization (ID-JAG, XAA) calls the same
routes as one signed in through OAuth, with an ID-JAG access token in place of the OAuth one.
`TeamAndOrgViewSetMixin` adds `IDJagAccessTokenAuthentication` to every view built on it. A view
that lists its own authentication classes has to name it, or that client gets a 401 where an
OAuth client succeeds.

To clear a violation, put `IDJagAccessTokenAuthentication` first in the view's
`authentication_classes`, so it runs before an authenticator that would reject a JWT outright.
Add the view to `OAUTH_ONLY_VIEWS` instead only when it must refuse ID-JAG tokens, with the reason.

    pytest posthog/test/repo_invariants/test_id_jag_accepted_with_oauth.py
"""

from rest_framework.schemas.generators import EndpointEnumerator

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import IDJagAccessTokenAuthentication, OAuthAccessTokenAuthentication

OAUTH_ONLY_VIEWS: dict[str, str] = {
    "posthog.api.oauth.ema_issuer.EmaTrustedIssuerView": (
        "Claude's partner-side setup registers an issuer with the client app's own OAuth token."
    ),
    "posthog.api.query_performance_proxy.QueryPerformanceProxyViewSet": (
        "INTERNAL scope, which an ID-JAG token cannot carry."
    ),
    "products.tasks.backend.presentation.views.api.LegacyDesktopAccessViewSet": (
        "Desktop gateway tokens are issued only to the desktop app's OAuth client."
    ),
    "posthog.api.user_integration.UserIntegrationViewSet": (
        "Lists teams across every organization of the user, and an ID-JAG token is confined to one."
    ),
}


def _dotted_name(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def test_routes_that_accept_oauth_accept_id_jag() -> None:
    violations = set()
    for path, _method, callback in EndpointEnumerator().get_api_endpoints():
        view_class = getattr(callback, "cls", None)
        if view_class is None or _dotted_name(view_class) in OAUTH_ONLY_VIEWS:
            continue
        if issubclass(view_class, TeamAndOrgViewSetMixin):
            continue
        # An `@action(authentication_classes=...)` replaces the view's classes for its own route.
        initkwargs = getattr(callback, "initkwargs", None) or {}
        classes = initkwargs.get("authentication_classes") or view_class.authentication_classes
        accepts_oauth = any(issubclass(cls, OAuthAccessTokenAuthentication) for cls in classes)
        accepts_id_jag = any(issubclass(cls, IDJagAccessTokenAuthentication) for cls in classes)
        if accepts_oauth and not accepts_id_jag:
            violations.add(f"{_dotted_name(view_class)} ({path})")

    assert not violations, (
        "These routes accept OAuth access tokens but not ID-JAG access tokens:\n  "
        + "\n  ".join(sorted(violations))
        + "\nSee the module docstring of this test for how to fix it."
    )
