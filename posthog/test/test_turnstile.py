from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings

import requests
from parameterized import parameterized

from posthog.turnstile import (
    CHALLENGE_NONCE_TTL_SECONDS,
    TURNSTILE_SITEVERIFY_URL,
    SiteverifyResult,
    _nonce_identity_hash,
    create_challenge_nonce,
    validate_and_consume_nonce,
    verify_login_turnstile_token,
    verify_turnstile_token,
)


class TestVerifyTurnstileToken(SimpleTestCase):
    @override_settings(CLOUDFLARE_TURNSTILE_SECRET_KEY="")
    def test_returns_false_when_no_secret_key(self):
        assert verify_turnstile_token("token", "1.2.3.4") is False

    @patch("posthog.turnstile.requests.post")
    @override_settings(CLOUDFLARE_TURNSTILE_SECRET_KEY="test_secret")
    def test_returns_true_on_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True}
        mock_post.return_value = mock_response

        assert verify_turnstile_token("valid_token", "1.2.3.4") is True
        mock_post.assert_called_once_with(
            TURNSTILE_SITEVERIFY_URL,
            data={"secret": "test_secret", "response": "valid_token", "remoteip": "1.2.3.4"},
            timeout=5.0,
        )

    @patch("posthog.turnstile.requests.post")
    @override_settings(CLOUDFLARE_TURNSTILE_SECRET_KEY="test_secret")
    def test_returns_false_on_failure(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": False, "error-codes": ["invalid-input-response"]}
        mock_post.return_value = mock_response

        assert verify_turnstile_token("bad_token", "1.2.3.4") is False

    @patch("posthog.turnstile.requests.post")
    @override_settings(CLOUDFLARE_TURNSTILE_SECRET_KEY="test_secret")
    def test_returns_false_on_timeout(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout("timeout")
        assert verify_turnstile_token("token", "1.2.3.4") is False

    @patch("posthog.turnstile.requests.post")
    @override_settings(CLOUDFLARE_TURNSTILE_SECRET_KEY="test_secret")
    def test_returns_false_on_exception(self, mock_post):
        mock_post.side_effect = Exception("unexpected")
        assert verify_turnstile_token("token", "1.2.3.4") is False


class TestChallengeNonce(TestCase):
    def setUp(self):
        from posthog.redis import get_client

        self.redis_client = get_client()

    def test_create_nonce_format(self):
        nonce = create_challenge_nonce("test@example.com", "1.2.3.4")
        parts = nonce.split(":")
        assert len(parts) == 3
        assert parts[0] == "challenge"
        expected_hash = _nonce_identity_hash("test@example.com", "1.2.3.4")
        assert parts[1] == expected_hash

    def test_create_nonce_stores_in_redis(self):
        nonce = create_challenge_nonce("test@example.com", "1.2.3.4")
        redis_key = f"turnstile_nonce:{nonce}"
        assert self.redis_client.exists(redis_key)
        ttl = self.redis_client.ttl(redis_key)
        assert 0 < ttl <= CHALLENGE_NONCE_TTL_SECONDS

    def test_validate_and_consume_success(self):
        nonce = create_challenge_nonce("test@example.com", "1.2.3.4")
        assert validate_and_consume_nonce(nonce, "test@example.com", "1.2.3.4") is True
        redis_key = f"turnstile_nonce:{nonce}"
        assert not self.redis_client.exists(redis_key)

    def test_validate_and_consume_single_use(self):
        nonce = create_challenge_nonce("test@example.com", "1.2.3.4")
        assert validate_and_consume_nonce(nonce, "test@example.com", "1.2.3.4") is True
        assert validate_and_consume_nonce(nonce, "test@example.com", "1.2.3.4") is False

    def test_validate_fails_with_wrong_email(self):
        nonce = create_challenge_nonce("test@example.com", "1.2.3.4")
        assert validate_and_consume_nonce(nonce, "other@example.com", "1.2.3.4") is False

    def test_validate_fails_with_wrong_ip(self):
        nonce = create_challenge_nonce("test@example.com", "1.2.3.4")
        assert validate_and_consume_nonce(nonce, "test@example.com", "5.6.7.8") is False

    def test_validate_fails_with_bad_format(self):
        assert validate_and_consume_nonce("invalid", "test@example.com", "1.2.3.4") is False
        assert validate_and_consume_nonce("challenge:abc", "test@example.com", "1.2.3.4") is False

    def test_validate_fails_with_expired_nonce(self):
        nonce = create_challenge_nonce("test@example.com", "1.2.3.4")
        redis_key = f"turnstile_nonce:{nonce}"
        self.redis_client.delete(redis_key)
        assert validate_and_consume_nonce(nonce, "test@example.com", "1.2.3.4") is False

    def test_identity_hash_is_case_insensitive_for_email(self):
        hash1 = _nonce_identity_hash("Test@Example.COM", "1.2.3.4")
        hash2 = _nonce_identity_hash("test@example.com", "1.2.3.4")
        assert hash1 == hash2


def _siteverify_response(status_code: int, body: object) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    if isinstance(body, Exception):
        response.json.side_effect = body
    else:
        response.json.return_value = body
    return response


REAL_SECRET = "real_secret"
TEST_PASS_SECRET = "1x0000000000000000000000000000000AA"


class TestVerifyLoginTurnstileToken(SimpleTestCase):
    @parameterized.expand(
        [
            ("login_action", REAL_SECRET, 200, {"success": True, "action": "login"}, SiteverifyResult.ACCEPTED, ()),
            (
                "other_action",
                REAL_SECRET,
                200,
                {"success": True, "action": "signup"},
                SiteverifyResult.REJECTED,
                ("action-mismatch",),
            ),
            (
                "no_action_on_real_secret",
                REAL_SECRET,
                200,
                {"success": True},
                SiteverifyResult.REJECTED,
                ("action-mismatch",),
            ),
            ("no_action_on_test_secret", TEST_PASS_SECRET, 200, {"success": True}, SiteverifyResult.ACCEPTED, ()),
            (
                "failure_with_codes",
                REAL_SECRET,
                200,
                {"success": False, "error-codes": ["invalid-input-response"]},
                SiteverifyResult.REJECTED,
                ("invalid-input-response",),
            ),
            (
                "internal_error",
                REAL_SECRET,
                200,
                {"success": False, "error-codes": ["internal-error"]},
                SiteverifyResult.UNAVAILABLE,
                ("internal-error",),
            ),
            ("server_error", REAL_SECRET, 502, ValueError("<html>"), SiteverifyResult.UNAVAILABLE, ()),
            ("bad_json", REAL_SECRET, 200, ValueError("not json"), SiteverifyResult.UNAVAILABLE, ()),
        ]
    )
    def test_maps_the_siteverify_answer(self, _name, secret, status_code, body, expected_result, expected_codes):
        with (
            override_settings(CLOUDFLARE_TURNSTILE_SECRET_KEY=secret),
            patch(
                "posthog.turnstile.turnstile_siteverify_request",
                return_value=_siteverify_response(status_code, body),
            ),
        ):
            outcome = verify_login_turnstile_token("tok", "1.2.3.4")

        assert (outcome.result, outcome.error_codes) == (expected_result, expected_codes)

    @parameterized.expand(
        [
            ("timeout", requests.exceptions.Timeout()),
            ("connection_error", requests.exceptions.ConnectionError()),
        ]
    )
    @override_settings(CLOUDFLARE_TURNSTILE_SECRET_KEY=REAL_SECRET)
    def test_network_failure_is_unavailable(self, _name, error):
        with patch("posthog.turnstile.turnstile_siteverify_request", side_effect=error):
            outcome = verify_login_turnstile_token("tok", "1.2.3.4")

        assert outcome.result == SiteverifyResult.UNAVAILABLE

    @override_settings(CLOUDFLARE_TURNSTILE_SECRET_KEY=REAL_SECRET)
    def test_oversized_token_is_rejected_without_a_call(self):
        with patch("posthog.turnstile.turnstile_siteverify_request") as siteverify:
            outcome = verify_login_turnstile_token("x" * 2049, "1.2.3.4")

        assert (outcome.result, outcome.error_codes) == (SiteverifyResult.REJECTED, ("token-too-long",))
        siteverify.assert_not_called()

    @override_settings(CLOUDFLARE_TURNSTILE_SECRET_KEY=REAL_SECRET)
    def test_sends_the_secret_token_and_ip_with_a_two_second_total_timeout(self):
        with patch(
            "posthog.turnstile.turnstile_siteverify_request",
            return_value=_siteverify_response(200, {"success": True, "action": "login"}),
        ) as siteverify:
            verify_login_turnstile_token("tok", "1.2.3.4")

        siteverify.assert_called_once_with(
            {"secret": REAL_SECRET, "response": "tok", "remoteip": "1.2.3.4"},
            source="login_turnstile",
            timeout=(0.5, 1.5),
        )
