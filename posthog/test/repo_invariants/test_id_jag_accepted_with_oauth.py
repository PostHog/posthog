"""A route that accepts OAuth access tokens accepts ID-JAG access tokens too.

An MCP client signed in through enterprise-managed authorization (ID-JAG, XAA) calls the same
routes as one signed in through OAuth, with an ID-JAG access token in place of the OAuth one.
`TeamAndOrgViewSetMixin` adds `IDJagAccessTokenAuthentication` to every view built on it. A view
that lists its own authentication classes has to name it, or that client gets a 401 where an
OAuth client succeeds.

Listing it is not enough. DRF stops at the first authenticator that raises, and the mixin runs a
view's own classes before ID-JAG. So every authenticator that runs before ID-JAG on a route must
return None for an ID-JAG token, the way `PersonalAPIKeyAuthentication` and
`ExportRendererAuthentication` do. The second test sends a signed ID-JAG token through those
authenticators on every route.

To clear a violation of the first test, put `IDJagAccessTokenAuthentication` first in the view's
`authentication_classes`, so it runs before an authenticator that would reject a JWT outright.
To clear a violation of the second test, make the named authenticator return None when
`IDJagAccessTokenAuthentication.is_id_jag_token(token)` is true. This directory runs without a
database, so an authenticator that looks the token up in the database instead of passing it on
fails with "Database access not allowed".
Add the view to `OAUTH_ONLY_VIEWS` instead only when it must refuse ID-JAG tokens, with the reason.

    pytest posthog/test/repo_invariants/test_id_jag_accepted_with_oauth.py
"""

import time
import uuid

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from rest_framework.request import Request
from rest_framework.schemas.generators import EndpointEnumerator

from posthog.api.id_jag import sign_access_token
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
    "posthog.api.user_push_token.UserPushTokenViewSet": (
        "Push delivery selects devices by user alone, so a device reaches every organization of the user."
    ),
    "products.ai_observability.backend.api.personal_spend.PersonalSpendViewSet": (
        "Spend is aggregated by email across every organization of the user."
    ),
    "products.ai_observability.backend.api.personal_spend.PersonalSpendEUProxyViewSet": (
        "Forwards to the US personal spend endpoint, which stays OAuth only."
    ),
    "products.signals.backend.views.SignalUserAutonomyConfigView": (
        "One config per user drives autonomous task starts in every organization of the user."
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


TOKEN_LIFETIME_SECONDS = 300


def _id_jag_access_token() -> str:
    site_url = settings.SITE_URL.rstrip("/")
    now = int(time.time())
    return sign_access_token(
        {
            "iss": site_url,
            "aud": site_url,
            "sub": "example.com:agent@example.com",
            "user_uuid": str(uuid.uuid4()),
            "client_id": "id-jag-invariant-client",
            "scope": "*",
            "org_id": str(uuid.uuid4()),
            "iat": now,
            "exp": now + TOKEN_LIFETIME_SECONDS,
        }
    )


def _request(method: str, path: str, authorization: str | None = None) -> Request:
    headers = {"Authorization": authorization} if authorization else None
    django_request = RequestFactory().generic(method, path, headers=headers)
    # AuthenticationMiddleware sets this on every real request, and SessionAuthentication reads it.
    django_request.user = AnonymousUser()
    return Request(django_request)


def _refuses_requests_without_its_credential(authenticator, method: str, path: str) -> bool:
    try:
        authenticator.authenticate(_request(method, path))
    except Exception:
        return True
    return False


def test_authenticators_before_id_jag_pass_its_token_on() -> None:
    token = _id_jag_access_token()
    violations = set()
    for path, method, callback in EndpointEnumerator().get_api_endpoints():
        view_class = getattr(callback, "cls", None)
        if view_class is None or _dotted_name(view_class) in OAUTH_ONLY_VIEWS:
            continue

        # An `@action(authentication_classes=...)` arrives in initkwargs, and a few views pick their
        # authenticators from the request, so build the view the way DRF does for this route.
        view = view_class(**(getattr(callback, "initkwargs", None) or {}))
        view.request = _request(method, path)
        authenticators = view.get_authenticators()
        id_jag_position = next(
            (
                i
                for i, authenticator in enumerate(authenticators)
                if isinstance(authenticator, IDJagAccessTokenAuthentication)
            ),
            None,
        )
        if id_jag_position is None:
            continue

        request = _request(method, path, authorization=f"Bearer {token}")
        for authenticator in authenticators[:id_jag_position]:
            if _refuses_requests_without_its_credential(authenticator, method, path):
                break
            try:
                claimed = authenticator.authenticate(request) is not None
                outcome = "accepts it"
            except Exception as error:
                claimed = True
                outcome = f"raises {type(error).__name__}: {error}"
            if claimed:
                violations.add(
                    f"{type(authenticator).__name__} {outcome} ({_dotted_name(view_class)}, {method} {path})"
                )

    assert not violations, (
        "These authenticators run before IDJagAccessTokenAuthentication but do not pass an ID-JAG token on:\n  "
        + "\n  ".join(sorted(violations))
        + "\nSee the module docstring of this test for how to fix it."
    )
