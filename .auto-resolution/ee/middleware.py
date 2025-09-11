import hashlib
import secrets
from collections.abc import Callable
from typing import cast
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

import jwt
import requests
import structlog

from posthog.models import User
from posthog.utils import get_ip_address, get_short_user_agent

logger = structlog.get_logger(__name__)


def get_admin_cookie_options(request: HttpRequest) -> dict:
    return {
        "max_age": 3600 * 6,  # 6 hours
        "path": "/admin/",
        "domain": None,
        "secure": settings.ADMIN_OAUTH2_COOKIE_SECURE,
        "httponly": True,
        "samesite": "Lax",  # Must be Lax because cookie is set on crossorigin redirect
    }


class AdminOAuth2Middleware:
    COOKIE_NAME = "ph_admin_verified"
    SESSION_VERIFICATION_SECRET_KEY = "admin_verification_secret"
    SESSION_VERIFICATION_HASH_KEY = "admin_verification_hash"
    SESSION_STATE_KEY = "admin_oauth2_state"
    SESSION_ORIGINAL_PATH_KEY = "admin_oauth2_original_path"

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response
        self.enabled = bool(settings.ADMIN_AUTH_GOOGLE_OAUTH2_KEY and settings.ADMIN_AUTH_GOOGLE_OAUTH2_SECRET)

    @staticmethod
    def _get_client_hash(request: HttpRequest) -> str:
        ip = get_ip_address(request)
        user_agent = get_short_user_agent(request)
        return hashlib.sha256(f"{ip}:{user_agent}".encode()).hexdigest()

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not self.enabled:
            return self.get_response(request)

        if not request.path.startswith("/admin/"):
            return self.get_response(request)

        if request.path == "/admin/oauth2/callback":
            return self.get_response(request)

        if not request.user.is_authenticated or not request.user.is_staff:
            return self.get_response(request)

        if not request.user.email:
            logger.error("admin_oauth2_no_user_email", user_id=request.user.id, username=request.user.username)
            return self.get_response(request)

        if self._is_oauth2_verified(request):
            return self.get_response(request)

        request.session[self.SESSION_ORIGINAL_PATH_KEY] = request.get_full_path()
        return self._redirect_to_oauth2(request)

    def _is_oauth2_verified(self, request: HttpRequest) -> bool:
        cookie_hash = request.COOKIES.get(self.COOKIE_NAME)
        session_secret = request.session.get(self.SESSION_VERIFICATION_SECRET_KEY)
        session_client_hash = request.session.get(self.SESSION_VERIFICATION_HASH_KEY)

        if not cookie_hash or not session_secret or not session_client_hash:
            return False

        # Verify cookie value matches session secret
        if not secrets.compare_digest(cookie_hash, hashlib.sha256(session_secret.encode()).hexdigest()):
            logger.error("admin_oauth2_cookie_mismatch", user=cast(User, request.user).email)
            return False

        # Verify client hasn't changed (IP/User-Agent)
        current_client_hash = self._get_client_hash(request)
        if current_client_hash != session_client_hash:
            logger.error(
                "admin_oauth2_client_changed",
                user=cast(User, request.user).email,
                ip=get_ip_address(request),
                user_agent=get_short_user_agent(request),
            )
            self._clear_verification(request)
            return False

        return True

    def _clear_verification(self, request: HttpRequest) -> None:
        keys_to_remove = [
            self.SESSION_VERIFICATION_SECRET_KEY,
            self.SESSION_VERIFICATION_HASH_KEY,
        ]
        for key in keys_to_remove:
            request.session.pop(key, None)

    def _redirect_to_oauth2(self, request: HttpRequest) -> HttpResponse:
        self._clear_verification(request)

        state = secrets.token_urlsafe(32)
        request.session[self.SESSION_STATE_KEY] = state

        params = {
            "client_id": settings.ADMIN_AUTH_GOOGLE_OAUTH2_KEY,
            "redirect_uri": request.build_absolute_uri("/admin/oauth2/callback"),
            "response_type": "code",
            "scope": "openid email",
            "state": state,
            "access_type": "online",
            "login_hint": cast(User, request.user).email,
        }

        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
        response = redirect(auth_url)

        cookie_options = get_admin_cookie_options(request)
        response.delete_cookie(self.COOKIE_NAME, path=cookie_options["path"], domain=cookie_options["domain"])
        return response


def admin_oauth2_callback(request: HttpRequest) -> HttpResponse:
    if not request.user.is_authenticated:
        return redirect("/admin/")

    error = request.GET.get("error")
    if error:
        logger.error("admin_oauth2_error", error=error, user=request.user.email)
        return redirect("/admin/")

    state = request.GET.get("state")
    saved_state = request.session.get(AdminOAuth2Middleware.SESSION_STATE_KEY)

    if not state or state != saved_state:
        logger.error("admin_oauth2_invalid_state", user=request.user.email)
        return redirect("/admin/")

    code = request.GET.get("code")
    if not code:
        return redirect("/admin/")

    try:
        token_data = _exchange_code_for_token(request, code)
        id_token = token_data.get("id_token", "")
        oauth_email = _get_email_from_id_token(id_token)
        user_email = cast(User, request.user).email.lower()

        if not oauth_email or not user_email:
            logger.error(
                "admin_oauth2_verification_failed",
                reason="missing_email",
                user_email=user_email,
                oauth_email=oauth_email,
            )
            return redirect("/")

        if oauth_email != user_email:
            logger.error(
                "admin_oauth2_verification_failed",
                reason="email_mismatch",
                user_email=user_email,
                oauth_email=oauth_email,
            )
            return redirect("/")

        verification_secret = secrets.token_urlsafe(32)

        request.session[AdminOAuth2Middleware.SESSION_VERIFICATION_SECRET_KEY] = verification_secret
        # bind the oauth2 session to the current IP + user agent
        request.session[AdminOAuth2Middleware.SESSION_VERIFICATION_HASH_KEY] = AdminOAuth2Middleware._get_client_hash(
            request
        )
        request.session.pop(AdminOAuth2Middleware.SESSION_STATE_KEY, None)

        original_path = request.session.pop(AdminOAuth2Middleware.SESSION_ORIGINAL_PATH_KEY, "/admin/")

        response = redirect(original_path)

        cookie_options = get_admin_cookie_options(request)
        secret_hash = hashlib.sha256(verification_secret.encode()).hexdigest()
        response.set_cookie(AdminOAuth2Middleware.COOKIE_NAME, value=secret_hash, **cookie_options)

        return response

    except Exception as e:
        logger.exception(
            "admin_oauth2_callback_error",
            error=str(e),
            user=request.user.email,
        )
        return redirect("/admin/")


def _exchange_code_for_token(request: HttpRequest, code: str) -> dict:
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": settings.ADMIN_AUTH_GOOGLE_OAUTH2_KEY,
        "client_secret": settings.ADMIN_AUTH_GOOGLE_OAUTH2_SECRET,
        "redirect_uri": request.build_absolute_uri("/admin/oauth2/callback"),
        "grant_type": "authorization_code",
    }
    response = requests.post(token_url, data=data)
    response.raise_for_status()
    return response.json()


def _get_email_from_id_token(id_token: str) -> str:
    try:
        from jwt import PyJWKClient

        # Set up Google's JWKS client
        jwks_client = PyJWKClient("https://www.googleapis.com/oauth2/v3/certs")

        # Get the signing key
        signing_key = jwks_client.get_signing_key_from_jwt(id_token)

        # Verify and decode the token
        payload = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.ADMIN_AUTH_GOOGLE_OAUTH2_KEY,
            issuer="https://accounts.google.com",
        )

        # email should always be verified, but simple sanity check doesn't hurt
        if payload.get("email_verified"):
            return payload.get("email", "").lower()
        return ""
    except Exception as e:
        logger.exception("admin_oauth2_id_token_decode_error", error=str(e))
        return ""
