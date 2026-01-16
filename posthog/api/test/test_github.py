import json

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import TestCase

from rest_framework import status

from posthog import redis
from posthog.api.github import (
    GITHUB_TYPE_FOR_PERSONAL_API_KEY,
    GITHUB_TYPE_FOR_PROJECT_SECRET,
    SignatureVerificationError,
    verify_github_signature,
)
from posthog.models import PersonalAPIKey
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal, mask_key_value


class TestGitHubSignatureVerification(TestCase):
    def setUp(self):
        self.redis_client = redis.get_client()
        # Clear any existing GitHub keys from cache
        for key in self.redis_client.scan_iter("github:public_key:*"):
            self.redis_client.delete(key)

        # Sample GitHub API response
        self.mock_github_response = {
            "public_keys": [
                {
                    "key_identifier": "test_kid_123",
                    "key": """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEX9k3r4gyp7ubiAUm4XLLnwGUApLO
dYtHUlWNMx0y6YwVG8nlBiJk2e0n+zpzs2WwszrnC7wfCqgU6rU3TkDvBQ==
-----END PUBLIC KEY-----""",
                },
                {
                    "key_identifier": "test_kid_456",
                    "key": """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEtest2X9k3r4gyp7ubiAUm4XLLnwG
UApLOdYtHUlWNMx0y6YwVG8nlBiJk2e0n+zpzs2WwszrnC7wfCqgU6rU3TkDvBQ==
-----END PUBLIC KEY-----""",
                },
            ]
        }

    @patch("posthog.api.github.requests.get")
    def test_caches_github_key_on_first_fetch(self, mock_get):
        """Test that the GitHub key is cached for 24 hours on first fetch."""
        mock_response = MagicMock()
        mock_response.json.return_value = self.mock_github_response
        mock_get.return_value = mock_response

        kid = "test_kid_123"
        cache_key = f"github:public_key:{kid}"

        # Verify cache is empty initially
        self.assertIsNone(self.redis_client.get(cache_key))

        # This would normally verify signature, but we're testing caching
        # so we'll catch the error from invalid signature
        with self.assertRaises(SignatureVerificationError):
            verify_github_signature("test_payload", kid, "invalid_sig")

        # Verify the key was cached
        cached_pem = self.redis_client.get(cache_key)
        self.assertIsNotNone(cached_pem)
        # Redis returns bytes, so decode it
        cached_pem_str = cached_pem.decode("utf-8") if isinstance(cached_pem, bytes) else cached_pem
        self.assertEqual(cached_pem_str, self.mock_github_response["public_keys"][0]["key"])

        # Verify GitHub API was called once
        mock_get.assert_called_once_with("https://api.github.com/meta/public_keys/secret_scanning", timeout=10)

    @patch("posthog.api.github.requests.get")
    def test_uses_cached_key_on_subsequent_calls(self, mock_get):
        """Test that cached key is used and GitHub API is not called again."""
        kid = "test_kid_123"
        cache_key = f"github:public_key:{kid}"
        expected_pem = self.mock_github_response["public_keys"][0]["key"]

        # Pre-populate cache using Redis directly
        self.redis_client.setex(cache_key, 60 * 60 * 24, expected_pem)  # 24 hours

        # Try to verify signature (will fail with invalid sig, but that's ok)
        with self.assertRaises(SignatureVerificationError):
            verify_github_signature("test_payload", kid, "invalid_sig")

        # Verify GitHub API was NOT called
        mock_get.assert_not_called()

    @patch("posthog.api.github.requests.get")
    def test_fetches_different_kids_independently(self, mock_get):
        """Test that different key identifiers are cached independently."""
        mock_response = MagicMock()
        mock_response.json.return_value = self.mock_github_response
        mock_get.return_value = mock_response

        kid1 = "test_kid_123"
        kid2 = "test_kid_456"

        # Fetch first kid
        with self.assertRaises(SignatureVerificationError):
            verify_github_signature("test_payload", kid1, "invalid_sig")

        # Fetch second kid
        with self.assertRaises(SignatureVerificationError):
            verify_github_signature("test_payload", kid2, "invalid_sig")

        # Verify both are cached separately
        cached_pem1 = self.redis_client.get(f"github:public_key:{kid1}")
        cached_pem2 = self.redis_client.get(f"github:public_key:{kid2}")

        self.assertIsNotNone(cached_pem1)
        self.assertIsNotNone(cached_pem2)
        # Decode bytes from Redis
        cached_pem1_str = cached_pem1.decode("utf-8") if isinstance(cached_pem1, bytes) else cached_pem1
        cached_pem2_str = cached_pem2.decode("utf-8") if isinstance(cached_pem2, bytes) else cached_pem2
        self.assertNotEqual(cached_pem1_str, cached_pem2_str)
        self.assertEqual(cached_pem1_str, self.mock_github_response["public_keys"][0]["key"])
        self.assertEqual(cached_pem2_str, self.mock_github_response["public_keys"][1]["key"])

        # GitHub API should be called twice (once for each kid)
        self.assertEqual(mock_get.call_count, 2)

    @patch("posthog.api.github.requests.get")
    def test_handles_github_api_failure(self, mock_get):
        """Test that GitHub API failures are handled gracefully."""
        mock_get.side_effect = Exception("Network error")

        kid = "test_kid_123"

        with self.assertRaises(SignatureVerificationError) as ctx:
            verify_github_signature("test_payload", kid, "invalid_sig")

        self.assertEqual(str(ctx.exception), "Failed to fetch GitHub public keys")

        # Verify nothing was cached
        self.assertIsNone(self.redis_client.get(f"github:public_key:{kid}"))

    @patch("posthog.api.github.requests.get")
    def test_handles_missing_kid_in_response(self, mock_get):
        """Test that missing key identifier in response is handled."""
        mock_response = MagicMock()
        mock_response.json.return_value = self.mock_github_response
        mock_get.return_value = mock_response

        kid = "non_existent_kid"

        with self.assertRaises(SignatureVerificationError) as ctx:
            verify_github_signature("test_payload", kid, "invalid_sig")

        self.assertEqual(str(ctx.exception), "No public key found matching key identifier")

        # Verify nothing was cached for non-existent kid
        self.assertIsNone(self.redis_client.get(f"github:public_key:{kid}"))

    @patch("posthog.api.github.requests.get")
    def test_handles_malformed_public_key(self, mock_get):
        """Test that malformed public key entries are handled."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "public_keys": [
                {
                    "key_identifier": "bad_kid",
                    "key": "",  # Empty key
                }
            ]
        }
        mock_get.return_value = mock_response

        kid = "bad_kid"

        with self.assertRaises(SignatureVerificationError) as ctx:
            verify_github_signature("test_payload", kid, "invalid_sig")

        self.assertEqual(str(ctx.exception), "Malformed public key entry")

        # Verify nothing was cached for malformed key
        self.assertIsNone(self.redis_client.get(f"github:public_key:{kid}"))


class TestSecretAlertEndpoint(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.redis_client = redis.get_client()
        # Clear any existing GitHub keys from cache
        for key in self.redis_client.scan_iter("github:public_key:*"):
            self.redis_client.delete(key)

        # Valid test payload (uses project secret type)
        self.valid_payload = [
            {
                "token": "phx_test_token_123",
                "type": GITHUB_TYPE_FOR_PROJECT_SECRET,
                "url": "https://github.com/posthog/posthog/blob/master/example.py",
                "source": "github",
            }
        ]

        # Mock GitHub response for signature verification
        self.mock_github_response = {
            "public_keys": [
                {
                    "key_identifier": "test_kid",
                    "key": """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEX9k3r4gyp7ubiAUm4XLLnwGUApLO
dYtHUlWNMx0y6YwVG8nlBiJk2e0n+zpzs2WwszrnC7wfCqgU6rU3TkDvBQ==
-----END PUBLIC KEY-----""",
                }
            ]
        }

    @patch("posthog.api.github.verify_github_signature")
    def test_secret_alert_with_valid_headers(self, mock_verify):
        """Test that secret alert endpoint processes valid requests."""
        mock_verify.return_value = None  # Signature verification passes

        response = self.client.post(
            "/api/alerts/github",
            data=json.dumps(self.valid_payload),
            content_type="application/json",
            headers={"github-public-key-identifier": "test_kid", "github-public-key-signature": "test_signature"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify response structure
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertIn("token_hash", data[0])
        self.assertIn("token_type", data[0])
        self.assertIn("label", data[0])
        self.assertEqual(data[0]["token_type"], GITHUB_TYPE_FOR_PROJECT_SECRET)

    def test_secret_alert_missing_headers(self):
        """Test that missing headers are rejected."""
        response = self.client.post(
            "/api/alerts/github", data=json.dumps(self.valid_payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        # Check that the error is about missing headers
        self.assertIn("Github-Public-Key-Identifier", str(data))

    @patch("posthog.api.github.verify_github_signature")
    def test_secret_alert_invalid_signature(self, mock_verify):
        """Test that invalid signatures are rejected."""
        mock_verify.side_effect = SignatureVerificationError("Invalid signature")

        response = self.client.post(
            "/api/alerts/github",
            data=json.dumps(self.valid_payload),
            content_type="application/json",
            headers={"github-public-key-identifier": "test_kid", "github-public-key-signature": "invalid_signature"},
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("posthog.api.github.requests.get")
    def test_request_body_accessible_for_signature_verification(self, mock_get):
        """Test that request.body is accessible for signature verification."""
        # Set up mock GitHub response
        mock_response = MagicMock()
        mock_response.json.return_value = self.mock_github_response
        mock_get.return_value = mock_response

        # This test doesn't mock verify_github_signature, so it actually tests the full flow
        # The signature will fail, but we're testing that we don't get RawPostDataException
        response = self.client.post(
            "/api/alerts/github",
            data=json.dumps(self.valid_payload),
            content_type="application/json",
            headers={"github-public-key-identifier": "test_kid", "github-public-key-signature": "invalid_signature"},
        )

        # Should get 401 for invalid signature, not 500 for RawPostDataException
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        # Verify the response is about signature, not about body access
        self.assertEqual(response.json(), {"detail": "Invalid signature"})

    def test_accepts_json_content_type(self):
        """Test that the endpoint accepts application/json content type (not 415 error)."""
        # Test without signature headers first to verify content type is accepted
        response = self.client.post(
            "/api/alerts/github",
            data=json.dumps(self.valid_payload),
            content_type="application/json",
        )

        # Should get 400 for missing headers, not 415 for unsupported content type
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST])
        # Verify it's complaining about headers, not content type
        data = response.json()
        self.assertIn("Github-Public-Key-Identifier", str(data))

    @patch("posthog.api.github.verify_github_signature")
    @patch("posthog.api.github.send_personal_api_key_exposed")
    def test_secret_alert_finds_and_rolls_existing_personal_api_key(self, mock_send_email, mock_verify):
        """Test that an existing personal API key is found, rolled, and email is sent."""
        mock_verify.return_value = None

        # Create a real key
        token = generate_random_token_personal()
        key = PersonalAPIKey.objects.create(
            user=self.user,
            label="Test Key",
            secure_value=hash_key_value(token),
            mask_value=mask_key_value(token),
        )
        original_secure_value = key.secure_value

        # Send alert with the token
        response = self.client.post(
            "/api/alerts/github",
            data=json.dumps(
                [
                    {
                        "token": token,
                        "type": GITHUB_TYPE_FOR_PERSONAL_API_KEY,
                        "url": "https://github.com/test/repo/blob/main/secrets.txt",
                        "source": "github",
                    }
                ]
            ),
            content_type="application/json",
            headers={"github-public-key-identifier": "test_kid", "github-public-key-signature": "test_sig"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["label"], "true_positive")
        self.assertEqual(data[0]["token_type"], GITHUB_TYPE_FOR_PERSONAL_API_KEY)

        # Verify key was rolled (secure_value changed)
        key.refresh_from_db()
        self.assertNotEqual(key.secure_value, original_secure_value)
        self.assertIsNotNone(key.last_rolled_at)

        # Verify email was sent
        mock_send_email.assert_called_once()
        call_args = mock_send_email.call_args
        self.assertEqual(call_args[0][0], self.user.id)
        self.assertEqual(call_args[0][1], key.id)

    @patch("posthog.api.github.verify_github_signature")
    def test_secret_alert_returns_false_positive_for_unknown_key(self, mock_verify):
        """Test that an unknown token returns false_positive."""
        mock_verify.return_value = None

        # Send alert with a non-existent token
        response = self.client.post(
            "/api/alerts/github",
            data=json.dumps(
                [
                    {
                        "token": "phx_nonexistent_token_12345678901234567890",
                        "type": GITHUB_TYPE_FOR_PERSONAL_API_KEY,
                        "url": "https://github.com/test/repo/blob/main/config.py",
                        "source": "github",
                    }
                ]
            ),
            content_type="application/json",
            headers={"github-public-key-identifier": "test_kid", "github-public-key-signature": "test_sig"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["label"], "false_positive")

    @patch("posthog.api.github.verify_github_signature")
    @patch("posthog.api.github.send_personal_api_key_exposed")
    def test_secret_alert_finds_key_with_legacy_pbkdf2_hash(self, mock_send_email, mock_verify):
        """Test that keys stored with legacy PBKDF2 hash are still found."""
        mock_verify.return_value = None

        # Create a key with legacy PBKDF2 hash (260000 iterations)
        token = generate_random_token_personal()
        legacy_hash = hash_key_value(token, mode="pbkdf2", iterations=260000)
        key = PersonalAPIKey.objects.create(
            user=self.user,
            label="Legacy Key",
            secure_value=legacy_hash,
            mask_value=mask_key_value(token),
        )

        # Send alert with the token
        response = self.client.post(
            "/api/alerts/github",
            data=json.dumps(
                [
                    {
                        "token": token,
                        "type": GITHUB_TYPE_FOR_PERSONAL_API_KEY,
                        "url": "https://github.com/test/repo/blob/main/old_secrets.txt",
                        "source": "github",
                    }
                ]
            ),
            content_type="application/json",
            headers={"github-public-key-identifier": "test_kid", "github-public-key-signature": "test_sig"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["label"], "true_positive")

        # Verify key was rolled
        key.refresh_from_db()
        self.assertIsNotNone(key.last_rolled_at)

    @patch("posthog.api.github.verify_github_signature")
    def test_secret_alert_does_not_find_key_for_inactive_user(self, mock_verify):
        """Test that keys for inactive users are not found (returns false_positive)."""
        mock_verify.return_value = None

        # Create a key for an inactive user
        self.user.is_active = False
        self.user.save()

        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="Inactive User Key",
            secure_value=hash_key_value(token),
            mask_value=mask_key_value(token),
        )

        # Send alert with the token
        response = self.client.post(
            "/api/alerts/github",
            data=json.dumps(
                [
                    {
                        "token": token,
                        "type": GITHUB_TYPE_FOR_PERSONAL_API_KEY,
                        "url": "https://github.com/test/repo/blob/main/inactive_secrets.txt",
                        "source": "github",
                    }
                ]
            ),
            content_type="application/json",
            headers={"github-public-key-identifier": "test_kid", "github-public-key-signature": "test_sig"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data), 1)
        # Key should NOT be found because user is inactive
        self.assertEqual(data[0]["label"], "false_positive")

    @patch("posthog.api.github.verify_github_signature")
    @patch("posthog.api.github.send_project_secret_api_key_exposed")
    def test_secret_alert_finds_project_secret_and_sends_email(self, mock_send_email, mock_verify):
        """Test that a project secret API key is found and email is sent to admins."""
        mock_verify.return_value = None

        # Set up a secret token on the team
        token = "phx_test_secret_token_1234567890"
        self.team.secret_api_token = token
        self.team.save()

        # Send alert with the token
        response = self.client.post(
            "/api/alerts/github",
            data=json.dumps(
                [
                    {
                        "token": token,
                        "type": GITHUB_TYPE_FOR_PROJECT_SECRET,
                        "url": "https://github.com/test/repo/blob/main/config.py",
                        "source": "github",
                    }
                ]
            ),
            content_type="application/json",
            headers={"github-public-key-identifier": "test_kid", "github-public-key-signature": "test_sig"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["label"], "true_positive")
        self.assertEqual(data[0]["token_type"], GITHUB_TYPE_FOR_PROJECT_SECRET)

        # Verify email task was called
        mock_send_email.assert_called_once()
        call_args = mock_send_email.call_args
        self.assertEqual(call_args[0][0], self.team.id)
        self.assertEqual(call_args[0][1], mask_key_value(token))
        self.assertIn("https://github.com/test/repo/blob/main/config.py", call_args[0][2])

    @patch("posthog.api.github.verify_github_signature")
    @patch("posthog.api.github.send_project_secret_api_key_exposed")
    def test_secret_alert_finds_project_secret_backup_and_sends_email(self, mock_send_email, mock_verify):
        """Test that a backup project secret API key is also detected."""
        mock_verify.return_value = None

        # Set up a backup secret token on the team
        token = "phx_test_backup_secret_token_123"
        self.team.secret_api_token = "phx_different_primary_token"
        self.team.secret_api_token_backup = token
        self.team.save()

        # Send alert with the backup token
        response = self.client.post(
            "/api/alerts/github",
            data=json.dumps(
                [
                    {
                        "token": token,
                        "type": GITHUB_TYPE_FOR_PROJECT_SECRET,
                        "url": "https://github.com/test/repo/blob/main/old_config.py",
                        "source": "github",
                    }
                ]
            ),
            content_type="application/json",
            headers={"github-public-key-identifier": "test_kid", "github-public-key-signature": "test_sig"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["label"], "true_positive")

        # Verify email task was called
        mock_send_email.assert_called_once()
