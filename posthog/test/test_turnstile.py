from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

import requests

from posthog.turnstile import (
    CHALLENGE_NONCE_TTL_SECONDS,
    TURNSTILE_SITEVERIFY_URL,
    _nonce_identity_hash,
    create_challenge_nonce,
    validate_and_consume_nonce,
    verify_turnstile_token,
)


class TestVerifyTurnstileToken(TestCase):
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
