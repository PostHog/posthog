from django.contrib.auth import BACKEND_SESSION_KEY
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

from loginas.utils import is_impersonated_session

from posthog.models import User
from posthog.session.dbsc import (
    binding as bindings,
    challenges,
    protocol,
)
from posthog.session.dbsc.cookies import CookieCheck, check_bound_cookie, cookie_name
from posthog.session.dbsc.events import record_refusal
from posthog.session.dbsc.owner import binding_owner
from posthog.session.dbsc.rollout import Mode, is_available, mode_for

REFUSED_REDIRECT = "/login?reason=session_unbound"


class DeviceBoundSessionMiddleware:
    """Only a copy of the session cookie taken off the device arrives at a bound session without the bound cookie."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not is_available() or request.path.startswith("/dbsc/"):
            return self.get_response(request)

        if isinstance(request.user, User) and BACKEND_SESSION_KEY in request.session:
            binding = bindings.current_binding(request.session)
            if binding is not None:
                return self._refuse(request, binding) or self.get_response(request)

        response = self.get_response(request)
        self._offer_registration(request, response)
        return response

    def _refuse(self, request: HttpRequest, binding: bindings.Binding) -> HttpResponse | None:
        check = check_bound_cookie(request.COOKIES.get(cookie_name()), binding.id)
        if check == CookieCheck.VALID:
            return None
        owner = binding_owner(request)
        mode = mode_for(owner) if owner is not None else Mode.OFF
        if mode == Mode.OFF:
            return None
        record_refusal(
            request,
            request.user,  # type: ignore[arg-type]  # checked to be a User by the caller
            mode=mode,
            reason=check.value,
            skipped=protocol.SKIPPED_HEADER in request.headers,
            impersonated=is_impersonated_session(request),
        )
        if mode != Mode.ENFORCE:
            return None
        request.session.flush()
        return HttpResponseRedirect(REFUSED_REDIRECT)

    def _offer_registration(self, request: HttpRequest, response: HttpResponse) -> None:
        offer_id = bindings.offer_id(request.session)
        if offer_id is None or bindings.is_bound_or_carried(request.session):
            return
        # After the login response, only page loads carry the offer, to spare API calls a cache round trip.
        is_login_response = request.session.modified
        is_page_load = request.headers.get("Sec-Fetch-Dest") == "document"
        if not (is_login_response or is_page_load):
            return
        challenge = challenges.issue_challenge(challenges.registration_subject(offer_id))
        response[protocol.REGISTRATION_HEADER] = protocol.registration_header_value(challenge)
