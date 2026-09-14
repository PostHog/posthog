import json
import time
import base64
import hashlib
import secrets
from collections.abc import Callable
from typing import Any

from unittest.mock import patch

from django.test import TestCase, override_settings

import jwt
import requests
from parameterized import parameterized
from social_core.backends.google import GoogleOAuth2

from ee.api.authentication import CustomGoogleOAuth2
from ee.api.google_oauth_diagnostics import FAILED_EVENT, SUCCEEDED_EVENT, TOKENINFO_URL, USERINFO_URL

ACCESS_TOKEN = "ya29.a0-fake-access-token-for-tests-0123456789abcdefghijklmnopqrstuvwxyz"
REFRESH_TOKEN = "1//fake-refresh-token-for-tests"
EMAIL = "someone@example.com"
SUB = "100000000000000000001"
USERINFO_ERROR_BODY = '{\n  "error": "invalid_request",\n  "error_description": "Invalid Credentials"\n}'


def _oidc_at_hash(access_token: str) -> str:
    digest = hashlib.sha256(access_token.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest[:16]).decode().rstrip("=")


def _token_response() -> dict[str, Any]:
    now = int(time.time())
    id_token = jwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": "fake-client-id",
            "azp": "fake-client-id",
            "sub": SUB,
            "email": EMAIL,
            "email_verified": True,
            "hd": "example.com",
            "at_hash": _oidc_at_hash(ACCESS_TOKEN),
            "iat": now,
            "exp": now + 3600,
        },
        secrets.token_hex(16),
        algorithm="HS256",
        headers={"kid": "fake-kid"},
    )
    return {
        "access_token": ACCESS_TOKEN,
        "refresh_token": REFRESH_TOKEN,
        "id_token": id_token,
        "expires_in": 3599,
        "scope": "openid https://www.googleapis.com/auth/userinfo.email",
        "token_type": "Bearer",
    }


def _response(status_code: int, body: str, url: str) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = body.encode()
    response.url = url
    response.headers["WWW-Authenticate"] = 'Bearer realm="https://accounts.google.com/", error="invalid_token"'
    return response


def _tokeninfo_answers() -> requests.Response:
    body = json.dumps({"aud": "fake-client-id", "sub": SUB, "email": EMAIL, "expires_in": "3500"})
    return _response(200, body, TOKENINFO_URL)


def _tokeninfo_unreachable() -> requests.Response:
    raise requests.ConnectionError(f"Max retries exceeded with url: /tokeninfo?access_token={ACCESS_TOKEN}")


class _InlineThread:
    def __init__(self, target: Callable[[], None], **_kwargs: Any) -> None:
        self._target = target

    def start(self) -> None:
        self._target()


@override_settings(GOOGLE_OAUTH_DIAGNOSTICS_FINGERPRINT_KEYS=["fake-fingerprint-key"])
class TestGoogleOAuthDiagnostics(TestCase):
    @parameterized.expand(
        [
            ("tokeninfo_answers", _tokeninfo_answers, None),
            ("tokeninfo_unreachable", _tokeninfo_unreachable, ["tokeninfo: ConnectionError"]),
        ]
    )
    def test_failed_userinfo_reraises_the_original_error_and_reports_no_secrets(
        self, _name: str, tokeninfo: Callable[[], requests.Response], expected_errors: list[str] | None
    ) -> None:
        token_response = _token_response()
        error = requests.HTTPError("401 Client Error", response=_response(401, USERINFO_ERROR_BODY, USERINFO_URL))

        def fake_request(_method: str, url: str, **_kwargs: Any) -> requests.Response:
            return _response(401, USERINFO_ERROR_BODY, USERINFO_URL) if url == USERINFO_URL else tokeninfo()

        with (
            patch.object(GoogleOAuth2, "user_data", side_effect=error),
            patch("posthog.egress.transport.transport.requests.request", side_effect=fake_request),
            patch("ee.api.google_oauth_diagnostics.RETRY_DELAY_SECONDS", 0),
            patch("ee.api.google_oauth_diagnostics.Thread", _InlineThread),
            patch("ee.api.google_oauth_diagnostics.posthoganalytics.capture") as capture,
            self.assertRaises(requests.HTTPError) as raised,
        ):
            CustomGoogleOAuth2().user_data(ACCESS_TOKEN, response=token_response)

        assert raised.exception is error
        capture.assert_called_once()
        event = capture.call_args.kwargs
        properties = event["properties"]
        assert event["event"] == FAILED_EVENT
        assert properties["userinfo_body"] == USERINFO_ERROR_BODY
        assert properties["retry_status"] == 401
        assert properties["id_token_at_hash_matches"] is True
        assert properties["id_token_email_fp"] is not None
        assert properties["$process_person_profile"] is False
        assert properties.get("diagnostics_errors") == expected_errors

        serialized = json.dumps(event, default=str)
        for secret in (ACCESS_TOKEN, REFRESH_TOKEN, token_response["id_token"], EMAIL, SUB):
            assert secret not in serialized

    def test_unreachable_userinfo_reraises_and_reports_without_probing_google(self) -> None:
        error = requests.ConnectionError("Connection refused")

        with (
            patch.object(GoogleOAuth2, "user_data", side_effect=error),
            patch("posthog.egress.transport.transport.requests.request") as outbound_request,
            patch("ee.api.google_oauth_diagnostics.posthoganalytics.capture") as capture,
            self.assertRaises(requests.ConnectionError) as raised,
        ):
            CustomGoogleOAuth2().user_data(ACCESS_TOKEN, response=_token_response())

        assert raised.exception is error
        outbound_request.assert_not_called()
        event = capture.call_args.kwargs
        assert event["event"] == FAILED_EVENT
        assert event["properties"]["userinfo_error"] == "ConnectionError"

    def test_successful_userinfo_passes_the_profile_through_and_stores_none_of_it(self) -> None:
        profile = {"sub": SUB, "email": EMAIL, "name": "Test Person", "picture": "https://example.com/avatar.png"}

        with (
            patch.object(GoogleOAuth2, "user_data", return_value=profile),
            patch("posthog.egress.transport.transport.requests.request") as outbound_request,
            patch("ee.api.google_oauth_diagnostics.posthoganalytics.capture") as capture,
        ):
            result = CustomGoogleOAuth2().user_data(ACCESS_TOKEN, response=_token_response())

        assert result is profile
        outbound_request.assert_not_called()
        event = capture.call_args.kwargs
        assert event["event"] == SUCCEEDED_EVENT

        serialized = json.dumps(event, default=str)
        for private in (ACCESS_TOKEN, EMAIL, SUB, profile["name"], profile["picture"]):
            assert private not in serialized
