"""Temporary diagnostics for Google OAuth `userinfo` failures.

This module records one PostHog event for each Google login, so that `userinfo` failures can be
diagnosed. It never changes the outcome of a login: the original result or error always passes through.

To remove it, delete this module, the `user_data` override in `CustomGoogleOAuth2`, and the
`GOOGLE_OAUTH_DIAGNOSTICS_FINGERPRINT_KEYS` setting.
"""

import hmac
import json
import time
import base64
import socket
import hashlib
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from importlib.metadata import PackageNotFoundError, version
from threading import BoundedSemaphore, Thread
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import get_user_model

import jwt
import requests
import posthoganalytics
from social_core.backends.google import GoogleOAuth2
from social_django.models import UserSocialAuth

from posthog.egress.google_workspace.transport import GoogleWorkspaceClient
from posthog.exceptions_capture import capture_exception

USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
RETRY_DELAY_SECONDS = 1.0
HTTP_CONNECT_READ_TIMEOUT_SECONDS = (2.0, 3.0)
MAX_CONCURRENT_PROBES = 2
EGRESS_SOURCE = "google_oauth_diagnostics"
FAILED_EVENT = "google oauth userinfo failed"
SUCCEEDED_EVENT = "google oauth userinfo succeeded"

Properties = dict[str, Any]

# Calls without a scope are recorded for volume but never gated, so a diagnostic call is never shed.
_EGRESS = GoogleWorkspaceClient()
_PROBE_SLOTS = BoundedSemaphore(MAX_CONCURRENT_PROBES)


def fetch_userinfo_with_diagnostics(
    backend: GoogleOAuth2,
    access_token: str,
    token_response: dict[str, Any],
    fetch: Callable[[], Any],
) -> Any:
    started = time.monotonic()
    try:
        user_data = fetch()
    except Exception as error:
        _report(backend, access_token, token_response, _elapsed_ms(started), error)
        raise
    _report(backend, access_token, token_response, _elapsed_ms(started), None)
    return user_data


def _report(
    backend: GoogleOAuth2,
    access_token: str,
    token_response: dict[str, Any],
    latency_ms: int,
    error: Exception | None,
) -> None:
    try:
        client_id = _client_id(backend)
        claims, id_token_properties = _id_token_properties(token_response.get("id_token"), access_token, client_id)
        properties = _collect(
            {
                "environment": _environment_properties,
                "token": lambda: _token_properties(access_token, token_response),
                "callback": lambda: _callback_properties(backend),
                "account": lambda: _account_properties(claims.get("email"), claims.get("sub")),
            }
        )
        properties.update(id_token_properties)
        properties["userinfo_latency_ms"] = latency_ms

        if error is None:
            _capture(SUCCEEDED_EVENT, properties)
            return

        properties.update(_collect({"userinfo": lambda: _userinfo_error_properties(error, access_token)}))
        # Only an answer from Google is worth probing. After a timeout or a connection error,
        # more calls to Google add load and tell us nothing new.
        if isinstance(error, requests.HTTPError):
            if _start_probes(lambda: _probe_and_capture(access_token, client_id, properties)):
                return
            properties["probes_skipped"] = "busy"
        _capture(FAILED_EVENT, properties)
    except Exception as diagnostics_error:
        _capture_diagnostics_error(diagnostics_error)


def _start_probes(job: Callable[[], None]) -> bool:
    # The probes wait and then call Google, so they run off the request thread and a failed login
    # does not hold a web worker. The slots cap how many run at once, so a burst of failed logins
    # cannot pile up threads or calls to Google.
    if not _PROBE_SLOTS.acquire(blocking=False):
        return False

    def run() -> None:
        try:
            job()
        finally:
            _PROBE_SLOTS.release()

    try:
        Thread(target=run, name="google-oauth-diagnostics", daemon=True).start()
    except Exception:
        _PROBE_SLOTS.release()
        return False
    return True


def _probe_and_capture(access_token: str, client_id: str | None, properties: Properties) -> None:
    try:
        properties.update(
            _collect(
                {
                    "retry": lambda: _retry_properties(access_token),
                    "tokeninfo": lambda: _tokeninfo_properties(access_token, client_id),
                }
            )
        )
        _capture(FAILED_EVENT, properties)
    except Exception as diagnostics_error:
        _capture_diagnostics_error(diagnostics_error)


def _capture(event: str, properties: Properties) -> None:
    posthoganalytics.capture(
        distinct_id=properties.get("id_token_email_fp") or properties.get("token_fp") or "google-oauth-diagnostics",
        event=event,
        properties={**properties, "$process_person_profile": False},
    )


def _capture_diagnostics_error(error: Exception) -> None:
    # The frames that raise here hold the access token and the ID token claims, so the capture
    # must not attach their local variables.
    with posthoganalytics.new_context():
        posthoganalytics.set_capture_exception_code_variables_context(False)
        capture_exception(error)


def _collect(sections: dict[str, Callable[[], Properties]]) -> Properties:
    # Only the exception class is kept: a message from `requests` can contain the request URL,
    # and the tokeninfo URL contains the access token.
    properties: Properties = {}
    errors: list[str] = []
    for name, build in sections.items():
        try:
            properties.update(build())
        except Exception as error:
            errors.append(f"{name}: {type(error).__name__}")
    if errors:
        properties["diagnostics_errors"] = errors
    return properties


def _environment_properties() -> Properties:
    return {
        "region": settings.CLOUD_DEPLOYMENT,
        "hostname": socket.gethostname(),
        "social_core_version": _package_version("social-auth-core"),
        "requests_version": requests.__version__,
        "egress_proxy": bool(requests.utils.get_environ_proxies(USERINFO_URL)),
    }


def _token_properties(access_token: str, token_response: dict[str, Any]) -> Properties:
    return {
        "token_length": len(access_token),
        # The first characters are Google's token format marker, such as "ya29.a0", and are not secret.
        "token_prefix": access_token[:7],
        "token_fp": _hash_random_value(access_token),
        "token_response_keys": sorted(token_response.keys()),
        "token_scope": token_response.get("scope"),
        "token_expires_in": token_response.get("expires_in"),
        "token_type": token_response.get("token_type"),
    }


def _callback_properties(backend: GoogleOAuth2) -> Properties:
    strategy = getattr(backend, "strategy", None)
    data = getattr(backend, "data", None) or {}
    request = getattr(strategy, "request", None)
    user = getattr(request, "user", None)
    return {
        "state_fp": _hash_random_value(data.get("state")),
        "code_fp": _hash_random_value(data.get("code")),
        "flow_origin": _first_path_segment(strategy.session_get("next") if strategy else None),
        "session_reauth": strategy.session_get("reauth") if strategy else None,
        "was_authenticated": bool(getattr(user, "is_authenticated", False)),
    }


def _id_token_properties(
    id_token: str | None, access_token: str, client_id: str | None
) -> tuple[dict[str, Any], Properties]:
    """Returns the raw claims for internal lookups, and the event properties. Never emit the raw claims."""
    if not id_token:
        return {}, {"id_token_present": False}
    try:
        header = jwt.get_unverified_header(id_token)
        # The claims are read for diagnostics only and are never trusted for authentication,
        # so the signature and the time and audience checks are all off.
        claims: dict[str, Any] = jwt.decode(
            id_token,
            options={
                "verify_signature": False,  # nosemgrep: python.jwt.security.unverified-jwt-decode.unverified-jwt-decode
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
                "verify_aud": False,
                "verify_iss": False,
            },
        )
    except Exception as error:
        return {}, {"id_token_present": True, "id_token_decode_error": type(error).__name__}

    email = claims.get("email")
    iat = claims.get("iat")
    at_hash = claims.get("at_hash")
    return claims, {
        "id_token_present": True,
        "id_token_alg": header.get("alg"),
        "id_token_kid": header.get("kid"),
        "id_token_typ": header.get("typ"),
        "id_token_iss": claims.get("iss"),
        "id_token_azp": claims.get("azp"),
        "id_token_aud": claims.get("aud"),
        "id_token_aud_matches_client": client_id is not None and claims.get("aud") == client_id,
        "id_token_iat": iat,
        "id_token_exp": claims.get("exp"),
        "id_token_auth_time": claims.get("auth_time"),
        "id_token_age_s": int(time.time()) - iat if isinstance(iat, int) else None,
        "id_token_nonce_present": "nonce" in claims,
        "id_token_email_verified": claims.get("email_verified"),
        "id_token_hd": claims.get("hd"),
        "id_token_email_domain": email.rsplit("@", 1)[-1].lower() if isinstance(email, str) else None,
        "id_token_email_fp": _fingerprint_identity(email.lower() if isinstance(email, str) else None),
        "id_token_sub_fp": _fingerprint_identity(claims.get("sub")),
        # at_hash is Google's hash of the access token that it issued with this ID token. A mismatch
        # means that the token sent to userinfo is not the token that Google issued.
        "id_token_at_hash_matches": _at_hash(access_token) == at_hash if isinstance(at_hash, str) else None,
    }


def _account_properties(email: Any, sub: Any) -> Properties:
    uids = [value for value in (sub, email) if isinstance(value, str)]
    linked_uids = set(
        UserSocialAuth.objects.filter(provider="google-oauth2", uid__in=uids).values_list("uid", flat=True)
    )
    return {
        "existing_user": isinstance(email, str) and get_user_model().objects.filter(email__iexact=email).exists(),
        "has_google_social_auth": bool(linked_uids),
        "social_auth_uid_type": "sub" if sub in linked_uids else "email" if email in linked_uids else None,
    }


def _userinfo_error_properties(error: Exception, access_token: str) -> Properties:
    response: requests.Response | None = error.response if isinstance(error, requests.HTTPError) else None
    if response is None:
        return {"userinfo_error": type(error).__name__}
    return {
        "userinfo_error": type(error).__name__,
        "userinfo_status": response.status_code,
        "userinfo_headers": _scrub_headers(response.headers, access_token),
        "userinfo_body": _scrub(response.text, access_token),
        "google_date_skew_s": _date_skew_seconds(response.headers.get("Date")),
    }


def _retry_properties(access_token: str) -> Properties:
    time.sleep(RETRY_DELAY_SECONDS)
    started = time.monotonic()
    response = _EGRESS.request(
        "GET",
        USERINFO_URL,
        source=EGRESS_SOURCE,
        endpoint="userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=HTTP_CONNECT_READ_TIMEOUT_SECONDS,
    )
    properties: Properties = {
        "retry_status": response.status_code,
        "retry_latency_ms": _elapsed_ms(started),
        "retry_headers": _scrub_headers(response.headers, access_token),
    }
    # A successful retry returns the user's profile, which is personal data and not a diagnostic.
    if response.status_code != 200:
        properties["retry_body"] = _scrub(response.text, access_token)
    return properties


def _tokeninfo_properties(access_token: str, client_id: str | None) -> Properties:
    started = time.monotonic()
    # The token goes in `params`, never in the URL string, because egress telemetry records the URL.
    response = _EGRESS.request(
        "GET",
        TOKENINFO_URL,
        source=EGRESS_SOURCE,
        endpoint="tokeninfo",
        params={"access_token": access_token},
        timeout=HTTP_CONNECT_READ_TIMEOUT_SECONDS,
    )
    body, parsed = _redact_tokeninfo_body(_scrub(response.text, access_token))
    return {
        "tokeninfo_status": response.status_code,
        "tokeninfo_latency_ms": _elapsed_ms(started),
        "tokeninfo_headers": _scrub_headers(response.headers, access_token),
        "tokeninfo_body": body,
        "tokeninfo_aud_matches_client": client_id is not None and parsed.get("aud") == client_id,
    }


def _redact_tokeninfo_body(body: str) -> tuple[str, dict[str, Any]]:
    try:
        parsed = json.loads(body)
    except ValueError:
        return body, {}
    if not isinstance(parsed, dict):
        return body, {}
    redacted = dict(parsed)
    if isinstance(redacted.get("email"), str):
        redacted["email_domain"] = redacted["email"].rsplit("@", 1)[-1].lower()
        redacted["email"] = _fingerprint_identity(redacted["email"].lower())
    if "sub" in redacted:
        redacted["sub"] = _fingerprint_identity(str(redacted["sub"]))
    return json.dumps(redacted), parsed


def _scrub(text: str, access_token: str) -> str:
    return text.replace(access_token, "[access_token]") if access_token else text


def _scrub_headers(headers: Any, access_token: str) -> dict[str, str]:
    return {name: _scrub(str(value), access_token) for name, value in headers.items()}


def _hash_random_value(value: str | None) -> str | None:
    # Tokens, codes and states are long random strings, so an unkeyed hash of one cannot be reversed.
    if not value:
        return None
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _fingerprint_identity(value: str | None) -> str | None:
    # An email address can be guessed, so it needs a keyed HMAC. The key has its own setting, and
    # the fingerprint is left out when that setting is empty.
    keys = settings.GOOGLE_OAUTH_DIAGNOSTICS_FINGERPRINT_KEYS
    if not value or not keys:
        return None
    message = f"google-oauth-diagnostics:{value}".encode()
    return hmac.new(keys[0].encode(), message, hashlib.sha256).hexdigest()[:16]


def _at_hash(access_token: str) -> str:
    digest = hashlib.sha256(access_token.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest[: len(digest) // 2]).decode().rstrip("=")


def _client_id(backend: GoogleOAuth2) -> str | None:
    try:
        return backend.get_key_and_secret()[0] or None
    except Exception:
        return None


def _first_path_segment(url: Any) -> str | None:
    # Only the first segment is kept, so that invite and object ids in the path are not stored.
    if not isinstance(url, str) or not url:
        return None
    return urlparse(url).path.strip("/").split("/")[0] or "/"


def _date_skew_seconds(date_header: str | None) -> int | None:
    if not date_header:
        return None
    return int(parsedate_to_datetime(date_header).timestamp() - time.time())


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
