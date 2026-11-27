import uuid
import ipaddress

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings

import requests
from parameterized import parameterized

from posthog.turnstile import (
    CHALLENGE_NONCE_TTL_SECONDS,
    OPEN_CHALLENGE_LIMIT,
    TURNSTILE_SITEVERIFY_URL,
    TooManyOpenChallenges,
    _nonce_identity_hash,
    consume_challenge_nonce,
    create_challenge_nonce,
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
        nonce = create_challenge_nonce("test@example.com", "1.2.3.4", action="signup")
        parts = nonce.split(":")
        assert len(parts) == 3
        assert parts[0] == "challenge"
        expected_hash = _nonce_identity_hash("test@example.com", "1.2.3.4")
        assert parts[1] == expected_hash

    def test_create_nonce_stores_in_redis(self):
        nonce = create_challenge_nonce("test@example.com", "1.2.3.4", action="signup")
        redis_key = f"turnstile_nonce:{nonce}"
        assert self.redis_client.exists(redis_key)
        ttl = self.redis_client.ttl(redis_key)
        assert 0 < ttl <= CHALLENGE_NONCE_TTL_SECONDS

    @parameterized.expand(
        [
            ("with a radar attempt", "radar_att_01ABC", "radar_att_01ABC"),
            ("without a radar attempt", "", ""),
        ]
    )
    def test_consume_returns_the_stored_attempt(self, _name, radar_attempt_id, expected):
        nonce = create_challenge_nonce(
            "test@example.com", "1.2.3.4", action="signup", radar_attempt_id=radar_attempt_id
        )
        assert consume_challenge_nonce(nonce, "test@example.com", "1.2.3.4", action="signup") == expected
        redis_key = f"turnstile_nonce:{nonce}"
        assert not self.redis_client.exists(redis_key)

    @parameterized.expand(
        [
            ("login_nonce_on_signup", "login", "signup", None),
            ("signup_nonce_on_login", "signup", "login", None),
            ("login_nonce_on_login", "login", "login", "radar_att_01ABC"),
            ("older_release_nonce_on_signup", None, "signup", "radar_att_01ABC"),
            ("older_release_nonce_on_login", None, "login", None),
        ]
    )
    def test_a_nonce_completes_only_the_action_that_issued_it(self, _name, issued_for, consumed_for, expected):
        if issued_for:
            nonce = create_challenge_nonce(
                "test@example.com", "1.2.3.4", action=issued_for, radar_attempt_id="radar_att_01ABC"
            )
        else:
            nonce = f"challenge:{_nonce_identity_hash('test@example.com', '1.2.3.4')}:older-release"
            self.redis_client.setex(f"turnstile_nonce:{nonce}", CHALLENGE_NONCE_TTL_SECONDS, "radar_att_01ABC")

        assert consume_challenge_nonce(nonce, "test@example.com", "1.2.3.4", action=consumed_for) == expected

    def test_only_unsolved_challenges_of_one_address_count_toward_its_open_challenge_limit(self):
        # A fresh IP, because the counts live in the shared Redis for the whole window
        ip = str(ipaddress.IPv6Address(uuid.uuid4().int))
        nonces = [create_challenge_nonce("busy@example.com", ip, action="login") for _ in range(OPEN_CHALLENGE_LIMIT)]

        with self.assertRaises(TooManyOpenChallenges):
            create_challenge_nonce("busy@example.com", ip, action="login")
        create_challenge_nonce("other@example.com", ip, action="login")

        consume_challenge_nonce(nonces[0], "busy@example.com", ip, action="login")

        create_challenge_nonce("busy@example.com", ip, action="login")

    def test_validate_and_consume_single_use(self):
        nonce = create_challenge_nonce("test@example.com", "1.2.3.4", action="signup")
        assert consume_challenge_nonce(nonce, "test@example.com", "1.2.3.4", action="signup") == ""
        assert consume_challenge_nonce(nonce, "test@example.com", "1.2.3.4", action="signup") is None

    def test_validate_fails_with_wrong_email(self):
        nonce = create_challenge_nonce("test@example.com", "1.2.3.4", action="signup")
        assert consume_challenge_nonce(nonce, "other@example.com", "1.2.3.4", action="signup") is None

    def test_validate_fails_with_wrong_ip(self):
        nonce = create_challenge_nonce("test@example.com", "1.2.3.4", action="signup")
        assert consume_challenge_nonce(nonce, "test@example.com", "5.6.7.8", action="signup") is None

    def test_validate_fails_with_bad_format(self):
        assert consume_challenge_nonce("invalid", "test@example.com", "1.2.3.4", action="signup") is None
        assert consume_challenge_nonce("challenge:abc", "test@example.com", "1.2.3.4", action="signup") is None

    def test_validate_fails_with_expired_nonce(self):
        nonce = create_challenge_nonce("test@example.com", "1.2.3.4", action="signup")
        redis_key = f"turnstile_nonce:{nonce}"
        self.redis_client.delete(redis_key)
        assert consume_challenge_nonce(nonce, "test@example.com", "1.2.3.4", action="signup") is None

    def test_identity_hash_is_case_insensitive_for_email(self):
        hash1 = _nonce_identity_hash("Test@Example.COM", "1.2.3.4")
        hash2 = _nonce_identity_hash("test@example.com", "1.2.3.4")
        assert hash1 == hash2
