"""The browser posts here with no CSRF token. A cross-site page cannot set `Sec-Secure-Session-Id`
without a CORS preflight, which this server never grants."""

import hmac

from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

import structlog
from loginas.utils import is_impersonated_session

from posthog.models import User
from posthog.session.dbsc import (
    binding as bindings,
    challenges,
    escalation,
    protocol,
)
from posthog.session.dbsc.cookies import COOKIE_MAX_AGE_SECONDS, set_bound_cookie
from posthog.session.dbsc.decisions import Action
from posthog.session.dbsc.events import record_refresh, record_refusal, record_registration
from posthog.session.dbsc.owner import binding_mode, client_platform
from posthog.session.dbsc.rollout import Mode, is_available, mode_for

logger = structlog.get_logger(__name__)


def _end_dbsc_session() -> HttpResponse:
    # The browser ends its DBSC session on a 4xx other than 403, 407 and 429.
    return HttpResponse(status=401)


def _challenge_response(binding_id: str) -> HttpResponse:
    response = HttpResponse(status=403)
    challenge = challenges.issue_challenge(challenges.refresh_subject(binding_id))
    response[protocol.CHALLENGE_HEADER] = protocol.challenge_header_value(challenge, binding_id)
    return response


def _send_next_challenge(response: HttpResponse, binding_id: str) -> None:
    """The browser keeps a challenge from any response, so its next refresh signs it without a 403 first.

    It lives as long as the bound cookie, because the browser refreshes shortly before that cookie expires.
    """
    try:
        challenge = challenges.issue_challenge(challenges.refresh_subject(binding_id), COOKIE_MAX_AGE_SECONDS)
    except Exception:
        # The next refresh then asks for a challenge with a 403, as it would without this header.
        logger.warning("dbsc_next_challenge_failed", exc_info=True)
        return
    response[protocol.CHALLENGE_HEADER] = protocol.challenge_header_value(challenge, binding_id)


@csrf_exempt
@require_POST
def start_session(request: HttpRequest) -> HttpResponse:
    user = request.user
    session = request.session
    offer_id = bindings.offer_id(session)
    if not is_available() or not isinstance(user, User) or session.session_key is None:
        record_registration("not_offered", user_id=getattr(user, "id", None))
        return HttpResponse(status=400)
    if offer_id is None:
        # Chrome registers once for each offer it saw, and the login response and the next page load both carry one.
        outcome = "duplicate" if bindings.current_binding(session) is not None else "not_offered"
        record_registration(outcome, user_id=user.id)
        return HttpResponse(status=400)
    if is_impersonated_session(request) or mode_for(user) == Mode.OFF:
        record_registration("not_offered", user_id=user.id)
        return HttpResponse(status=400)

    token = protocol.parse_sf_string(request.headers.get(protocol.RESPONSE_HEADER))
    if token is None:
        record_registration("missing_proof", user_id=user.id)
        return HttpResponse(status=400)
    try:
        proof = protocol.verify_registration_proof(token)
    except protocol.ProofError as error:
        record_registration(f"invalid_proof:{error}", user_id=user.id)
        return HttpResponse(status=400)
    if proof.jwk is None or not challenges.consume_challenge(challenges.registration_subject(offer_id), proof.jti):
        record_registration("stale_challenge", user_id=user.id)
        return HttpResponse(status=400)

    binding = bindings.new_binding(alg=proof.alg, jwk=proof.jwk, platform=client_platform(request))
    if not bindings.save_binding(session.session_key, binding):
        record_registration("already_bound", user_id=user.id)
        return HttpResponse(status=409)
    session.pop(bindings.OFFER_SESSION_KEY, None)

    response = JsonResponse(protocol.session_config(binding.id))
    set_bound_cookie(response, binding.id)
    _send_next_challenge(response, binding.id)
    record_registration("bound", user_id=user.id)
    return response


@csrf_exempt
@require_POST
def refresh_session(request: HttpRequest) -> HttpResponse:
    user = request.user
    if not is_available():
        # A 5xx keeps the browser's DBSC session, so turning DBSC back on finds the bindings still usable.
        record_refresh("unavailable", user_id=None)
        return HttpResponse(status=503)
    session_id = protocol.parse_sf_string(request.headers.get(protocol.SESSION_ID_HEADER))
    if session_id is None:
        record_refresh("missing_session_id", user_id=None)
        return HttpResponse(status=400)
    if not isinstance(user, User) or request.session.session_key is None:
        record_refresh("no_session", user_id=None)
        return _end_dbsc_session()

    binding = bindings.current_binding(request.session)
    if binding is None or not hmac.compare_digest(binding.id.encode(), session_id.encode()):
        record_refresh("unknown_session", user_id=user.id)
        return _end_dbsc_session()

    token = protocol.parse_sf_string(request.headers.get(protocol.RESPONSE_HEADER))
    if token is None:
        record_refresh("challenged", user_id=user.id)
        return _challenge_response(binding.id)
    try:
        proof = protocol.verify_refresh_proof(token, binding)
    except protocol.ProofError:
        mode = binding_mode(request, binding)
        record_refresh("invalid_proof", user_id=user.id)
        if mode != Mode.OFF:
            record_refusal(
                request,
                user,
                binding_id=binding.id,
                mode=mode,
                reason="invalid_proof",
                action=Action.END_SESSION if mode == Mode.ENFORCE else Action.RECORD,
                skipped=False,
                cross_site=False,
                impersonated=is_impersonated_session(request),
            )
        if mode == Mode.ENFORCE:
            logout(request)
        return _end_dbsc_session()
    if not challenges.consume_challenge(challenges.refresh_subject(binding.id), proof.jti):
        record_refresh("stale_challenge", user_id=user.id)
        return _challenge_response(binding.id)

    # An empty body tells the browser to keep the session config it has.
    response = HttpResponse(status=200)
    set_bound_cookie(response, binding.id)
    _send_next_challenge(response, binding.id)
    record_refresh("refreshed", user_id=user.id)
    escalation.mark_refresh_healthy()
    return response
