"""A route that accepts OAuth access tokens accepts ID-JAG access tokens too.

An MCP client signed in through enterprise-managed authorization (ID-JAG, XAA) calls the same
routes as one signed in through OAuth, with an ID-JAG access token in place of the OAuth one.
`TeamAndOrgViewSetMixin` adds `IDJagAccessTokenAuthentication` to every view built on it, after the
classes that the view lists itself. DRF stops at the first authenticator that raises. So an earlier
class that reads an ID-JAG token as its own credential and rejects it gives that client a 401 where
an OAuth client succeeds. `PersonalAPIKeyAuthentication` does this to every bearer token without
the OAuth prefix.

So on every route that accepts OAuth, `IDJagAccessTokenAuthentication` must run before every
authenticator that is not in `IGNORES_ID_JAG_TOKENS`.

To clear a violation, put `IDJagAccessTokenAuthentication` first in the view's
`authentication_classes`. Add a class to `IGNORES_ID_JAG_TOKENS` only after you read its
`authenticate` and confirm that it returns None for an `at+jwt` bearer token.
Add the view to `OAUTH_ONLY_VIEWS` instead only when it must refuse ID-JAG tokens, with the reason.

    pytest posthog/test/repo_invariants/test_id_jag_accepted_with_oauth.py
"""

import time
from types import SimpleNamespace

import pytest

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.utils.module_loading import import_string

from rest_framework.request import Request
from rest_framework.schemas.generators import EndpointEnumerator

from posthog.api.id_jag import sign_access_token
from posthog.auth import IDJagAccessTokenAuthentication, OAuthAccessTokenAuthentication

# Exact classes by dotted name, not their subclasses, because a subclass can read the token differently.
IGNORES_ID_JAG_TOKENS: dict[str, str] = {
    "posthog.auth.SessionAuthentication": "Reads the session cookie, not the Authorization header.",
    "posthog.auth.OAuthAccessTokenAuthentication": "Reads only `pha_` bearer tokens.",
    "posthog.auth.ProjectSecretAPIKeyAuthentication": "Reads only `phs_` bearer tokens.",
    "posthog.auth.SharingAccessTokenAuthentication": "Reads the `sharing_access_token` query parameter.",
    "posthog.auth.SharingPasswordProtectedAuthentication": (
        "Returns None when a bearer JWT fails its own audience or algorithm check."
    ),
    "products.skills.backend.marketplace.auth.MarketplaceGitBasicAuthentication": "Reads only Basic credentials.",
}

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
    "posthog.api.user_push_token.UserPushTokenViewSet": (
        "Push delivery selects devices by user alone, so a device reaches every organization of the user."
    ),
    "products.ai_observability.backend.api.personal_spend.PersonalSpendViewSet": (
        "Spend is aggregated by email across every organization of the user."
    ),
    "products.ai_observability.backend.api.personal_spend.PersonalSpendEUProxyViewSet": (
        "Forwards to the US personal spend endpoint, which stays OAuth only."
    ),
    "products.workflows.backend.presentation.views.hog_flow.InternalHogFlowViewSet": (
        "Internal service endpoint. InternalAPIAuthentication runs first and refuses any request without the internal secret."
    ),
    "products.signals.backend.presentation.activity_summary.ActivitySummaryMembersViewSet": (
        "INTERNAL scope `signal_scout_internal`, which an ID-JAG token cannot carry."
    ),
    "products.signals.backend.scout_harness.views.SignalScoutMembersViewSet": (
        "INTERNAL scope `signal_scout_internal`, which an ID-JAG token cannot carry."
    ),
    "products.signals.backend.scout_harness.views.SignalScoutReportDiscussionsViewSet": (
        "INTERNAL scope `signal_scout_internal`, which an ID-JAG token cannot carry."
    ),
    "products.signals.backend.views.SignalUserAutonomyConfigView": (
        "One config per user drives autonomous task starts in every organization of the user."
    ),
}


def _dotted_name(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _authenticators_before_id_jag(view_class: type, initkwargs: dict, path: str) -> list[type] | None:
    """The authenticators that run before ID-JAG on a route that accepts OAuth, or None when ID-JAG never runs."""
    # An `@action(authentication_classes=...)` replaces the view's classes for its own route through `initkwargs`.
    view = view_class(**initkwargs)
    # DRF sets `request` before it calls `get_authenticators`, and some overrides read its method or path.
    view.request = SimpleNamespace(method="GET", path=path)
    authenticators = [type(authenticator) for authenticator in view.get_authenticators()]
    if not any(issubclass(cls, OAuthAccessTokenAuthentication) for cls in authenticators):
        return []
    for index, cls in enumerate(authenticators):
        if issubclass(cls, IDJagAccessTokenAuthentication):
            return authenticators[:index]
    return None


def test_routes_that_accept_oauth_accept_id_jag() -> None:
    violations = set()
    for path, _method, callback in EndpointEnumerator().get_api_endpoints():
        view_class = getattr(callback, "cls", None)
        if view_class is None or _dotted_name(view_class) in OAUTH_ONLY_VIEWS:
            continue
        before = _authenticators_before_id_jag(view_class, getattr(callback, "initkwargs", None) or {}, path)
        if before is None:
            violations.add(f"{_dotted_name(view_class)} ({path}): no IDJagAccessTokenAuthentication")
            continue
        rejecting = sorted(cls.__name__ for cls in before if _dotted_name(cls) not in IGNORES_ID_JAG_TOKENS)
        if rejecting:
            violations.add(f"{_dotted_name(view_class)} ({path}): runs {', '.join(rejecting)} first")

    assert not violations, (
        "These routes accept OAuth access tokens but not ID-JAG access tokens:\n  "
        + "\n  ".join(sorted(violations))
        + "\nSee the module docstring of this test for how to fix it."
    )


@pytest.mark.parametrize("dotted_name", sorted(IGNORES_ID_JAG_TOKENS))
def test_ignored_authenticators_return_none_for_an_id_jag_token(dotted_name: str) -> None:
    now = int(time.time())
    token = sign_access_token(
        {
            "iss": "http://localhost:8010",
            "aud": "http://localhost:8010",
            "sub": "example.com:user@example.com",
            "user_uuid": "00000000-0000-0000-0000-000000000000",
            "client_id": "id-jag-test-client",
            "scope": "user:read",
            "org_id": "00000000-0000-0000-0000-000000000000",
            "iat": now,
            "exp": now + 300,
        }
    )
    assert IDJagAccessTokenAuthentication.is_id_jag_token(token)
    # GET, because some authenticators read a bearer token only on GET.
    django_request = RequestFactory().get("/api/projects/1/", HTTP_AUTHORIZATION=f"Bearer {token}")
    django_request.user = AnonymousUser()

    assert import_string(dotted_name)().authenticate(Request(django_request)) is None
