from collections.abc import Callable
from typing import cast
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, logout
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers

import structlog
from loginas.utils import is_impersonated_session

from posthog.models import User
from posthog.session.dbsc import (
    binding as bindings,
    challenges,
    escalation,
    protocol,
)
from posthog.session.dbsc.cookies import CookieCheck, check_bound_cookie, cookie_name
from posthog.session.dbsc.decisions import Action, BoundRequest, decide
from posthog.session.dbsc.events import RefusalReason, record_refusal
from posthog.session.dbsc.owner import binding_mode
from posthog.session.dbsc.paths import ENDPOINT_PATHS
from posthog.session.dbsc.rollout import is_available

logger = structlog.get_logger(__name__)

# The same answers as a session-risk sign-out and DRF's own 401, so a refusal does not tell a cookie copy why it failed.
REFUSED_REDIRECT = "/login?reason=session_risk"
_NOT_AUTHENTICATED_BODY = {
    "type": "authentication_error",
    "code": "not_authenticated",
    "detail": "Authentication credentials were not provided.",
    "attr": None,
}
BOUNCE_COOKIE = "ph_dbsc_bounce"
BOUNCE_COOKIE_MAX_AGE_SECONDS = 30
# A meta refresh needs no script under the Content Security Policy, and our own origin starts the reload.
_BOUNCE_PAGE = '<!doctype html><meta http-equiv="refresh" content="0"><title>PostHog</title>'
_CROSS_SITE_FETCH_SITES = ("cross-site", "same-site")
_SESSION_KEEPING_ACTIONS = (Action.BOUNCE, Action.REJECT, Action.RETRY_LATER)


def _unauthenticated_response(request: HttpRequest) -> HttpResponse:
    """The app fetches /api/ paths, and a fetch that follows a redirect to the login page gets HTML it cannot read."""
    if request.path.startswith("/api/"):
        return JsonResponse(_NOT_AUTHENTICATED_BODY, status=401)
    return HttpResponseRedirect(REFUSED_REDIRECT)


def _bounce_response() -> HttpResponse:
    response = HttpResponse(_BOUNCE_PAGE, content_type="text/html")
    add_never_cache_headers(response)
    response.set_cookie(
        BOUNCE_COOKIE,
        "1",
        max_age=BOUNCE_COOKIE_MAX_AGE_SECONDS,
        path="/",
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=True,
        samesite="Lax",
    )
    return response


def _retry_later_response() -> HttpResponse:
    response = HttpResponse("PostHog could not check this session. Try again in a moment.", status=503)
    response["Retry-After"] = "10"
    return response


def _started_elsewhere(request: HttpRequest, navigation: bool) -> bool:
    """Whether the browser could not have refreshed for this request, because our own origin did not start it."""
    if request.headers.get("Sec-Fetch-Site") in _CROSS_SITE_FETCH_SITES:
        return True
    # An extension's request carries its own origin, and Sec-Fetch-Site "none" outside a navigation.
    origin = request.headers.get("Origin")
    if origin is not None and urlsplit(origin).netloc != request.get_host():
        return True
    return not navigation and request.headers.get("Sec-Fetch-Site") == "none"


def _bound_request(request: HttpRequest, binding: bindings.Binding, check: CookieCheck) -> BoundRequest:
    navigation = request.method == "GET" and request.headers.get("Sec-Fetch-Mode") == "navigate"
    return BoundRequest(
        check=check,
        mode=binding_mode(request, binding),
        binding_age=timezone.now() - binding.bound_at,
        cross_site=_started_elsewhere(request, navigation),
        navigation=navigation,
        bounced=BOUNCE_COOKIE in request.COOKIES,
        refresh_skipped=protocol.SKIPPED_HEADER in request.headers,
    )


def _refusal(request: HttpRequest, user: User, binding: bindings.Binding) -> HttpResponse | None:
    check = check_bound_cookie(request.COOKIES.get(cookie_name()), binding.id)
    # Most requests carry a valid cookie, so they skip the flag evaluation and the impersonation lookup.
    if check == CookieCheck.VALID:
        return None
    facts = _bound_request(request, binding, check)
    action = decide(facts)
    if action == Action.ALLOW:
        return None
    escalated = action in _SESSION_KEEPING_ACTIONS and escalation.is_repeated(binding.id)
    if escalated:
        action = Action.END_SESSION
    record_refusal(
        request,
        user,
        mode=facts.mode,
        reason=cast(RefusalReason, facts.check.value),
        action=action,
        skipped=facts.refresh_skipped,
        cross_site=facts.cross_site,
        impersonated=is_impersonated_session(request),
        escalated=escalated,
    )
    if action == Action.RECORD:
        return None
    if action == Action.BOUNCE:
        return _bounce_response()
    if action == Action.RETRY_LATER:
        return _retry_later_response()
    if action == Action.END_SESSION:
        # logout() rather than a bare flush, so the logout receivers revoke what an impersonation minted.
        logout(request)
    return _unauthenticated_response(request)


def _offer_registration(request: HttpRequest, response: HttpResponse) -> None:
    offer_id = bindings.offer_id(request.session)
    if offer_id is None or bindings.is_bound_or_carried(request.session):
        return
    # After the login response, only page loads carry the offer, to spare API calls a cache round trip.
    if not (bindings.is_login_response(request) or request.headers.get("Sec-Fetch-Dest") == "document"):
        return
    try:
        challenge = challenges.issue_challenge(challenges.registration_subject(offer_id))
    except Exception:
        # The offer comes back on the next page load, and a login must not fail because the cache is down.
        logger.warning("dbsc_offer_failed", exc_info=True)
        return
    response[protocol.REGISTRATION_HEADER] = protocol.registration_header_value(challenge)


class DeviceBoundSessionMiddleware:
    """Only a copy of the session cookie taken off the device arrives at a bound session without the bound cookie."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not is_available() or request.path in ENDPOINT_PATHS:
            return self.get_response(request)

        user = request.user
        if isinstance(user, User) and BACKEND_SESSION_KEY in request.session:
            binding = bindings.current_binding(request.session)
            if binding is not None:
                refusal = _refusal(request, user, binding)
                if refusal is not None:
                    return refusal

        response = self.get_response(request)
        # A view can log in another account, which replaces a bound session with one that has an offer.
        _offer_registration(request, response)
        return response
