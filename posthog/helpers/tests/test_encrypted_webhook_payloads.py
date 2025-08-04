from unittest.mock import patch, MagicMock
import pytest
from django.conf import settings

from posthog.helpers.encrypted_flag_payloads import encrypt_webhook_payloads
from posthog.temporal.common.codec import EncryptionCodec
from posthog.test.base import BaseTest


class TestEncryptWebhookPayloads(BaseTest):
    def setUp(self):
        super().setUp()
        self.codec = EncryptionCodec(settings)

    def test_encrypt_webhook_payloads_with_headers(self):
        """Test that webhook headers are encrypted while URL remains unencrypted"""
        validated_data = {
            "webhook_subscriptions": [
                {
                    "url": "https://example.com/webhook",
                    "headers": {"Authorization": "Bearer secret123", "X-Custom-Header": "sensitive-value"},
                }
            ]
        }

        original_url = validated_data["webhook_subscriptions"][0]["url"]
        original_auth = validated_data["webhook_subscriptions"][0]["headers"]["Authorization"]
        original_custom = validated_data["webhook_subscriptions"][0]["headers"]["X-Custom-Header"]

        encrypt_webhook_payloads(validated_data)

        # URL should remain unchanged
        assert validated_data["webhook_subscriptions"][0]["url"] == original_url

        # Headers should be encrypted
        encrypted_auth = validated_data["webhook_subscriptions"][0]["headers"]["Authorization"]
        encrypted_custom = validated_data["webhook_subscriptions"][0]["headers"]["X-Custom-Header"]

        assert encrypted_auth != original_auth
        assert encrypted_custom != original_custom

        # Verify we can decrypt back to original values
        decrypted_auth = self.codec.decrypt(encrypted_auth.encode("utf-8")).decode("utf-8")
        decrypted_custom = self.codec.decrypt(encrypted_custom.encode("utf-8")).decode("utf-8")

        assert decrypted_auth == original_auth
        assert decrypted_custom == original_custom

    def test_encrypt_webhook_payloads_multiple_subscriptions(self):
        """Test encryption with multiple webhook subscriptions"""
        validated_data = {
            "webhook_subscriptions": [
                {"url": "https://example1.com/webhook", "headers": {"Authorization": "Bearer token1"}},
                {"url": "https://example2.com/webhook", "headers": {"Authorization": "Bearer token2"}},
            ]
        }

        original_tokens = [
            validated_data["webhook_subscriptions"][0]["headers"]["Authorization"],
            validated_data["webhook_subscriptions"][1]["headers"]["Authorization"],
        ]

        encrypt_webhook_payloads(validated_data)

        # Both URLs should remain unchanged
        assert validated_data["webhook_subscriptions"][0]["url"] == "https://example1.com/webhook"
        assert validated_data["webhook_subscriptions"][1]["url"] == "https://example2.com/webhook"

        # Both tokens should be encrypted and different
        encrypted_tokens = [
            validated_data["webhook_subscriptions"][0]["headers"]["Authorization"],
            validated_data["webhook_subscriptions"][1]["headers"]["Authorization"],
        ]

        assert encrypted_tokens[0] != original_tokens[0]
        assert encrypted_tokens[1] != original_tokens[1]
        assert encrypted_tokens[0] != encrypted_tokens[1]  # Different encryption for different values

    def test_encrypt_webhook_payloads_with_non_string_values(self):
        """Test that non-string values are not encrypted"""
        validated_data = {
            "webhook_subscriptions": [
                {
                    "url": "https://example.com/webhook",
                    "headers": {
                        "Authorization": "Bearer secret",
                        "Content-Length": 12345,  # number in headers
                        "X-Retry": True,  # boolean in headers
                    },
                }
            ]
        }

        original_content_length = validated_data["webhook_subscriptions"][0]["headers"]["Content-Length"]
        original_retry = validated_data["webhook_subscriptions"][0]["headers"]["X-Retry"]
        original_auth = validated_data["webhook_subscriptions"][0]["headers"]["Authorization"]

        encrypt_webhook_payloads(validated_data)

        # Non-string values should remain unchanged
        assert validated_data["webhook_subscriptions"][0]["headers"]["Content-Length"] == original_content_length
        assert validated_data["webhook_subscriptions"][0]["headers"]["X-Retry"] == original_retry

        # String values should be encrypted
        assert validated_data["webhook_subscriptions"][0]["headers"]["Authorization"] != original_auth

    def test_encrypt_webhook_payloads_empty_array(self):
        """Test that function handles empty webhook_subscriptions array"""
        validated_data = {"webhook_subscriptions": []}

        encrypt_webhook_payloads(validated_data)

        assert validated_data["webhook_subscriptions"] == []

    def test_encrypt_webhook_payloads_null_value(self):
        """Test that function handles null webhook_subscriptions"""
        validated_data = {"webhook_subscriptions": None}

        encrypt_webhook_payloads(validated_data)

        assert validated_data["webhook_subscriptions"] is None

    def test_encrypt_webhook_payloads_encryption_error(self):
        """Test error handling when encryption fails"""
        validated_data = {
            "webhook_subscriptions": [
                {"url": "https://example.com/webhook", "headers": {"Authorization": "Bearer secret"}}
            ]
        }

        with patch("posthog.helpers.encrypted_flag_payloads.EncryptionCodec") as mock_codec_class:
            mock_codec = MagicMock()
            mock_codec.encrypt.side_effect = Exception("Encryption failed")
            mock_codec_class.return_value = mock_codec

            with pytest.raises(ValueError, match="Failed to encrypt dict field 'Authorization'"):
                encrypt_webhook_payloads(validated_data)

    def test_encrypt_webhook_payloads_deterministic_encryption(self):
        """Test that encryption produces consistent but different results each time"""
        validated_data1 = {
            "webhook_subscriptions": [
                {"url": "https://example.com/webhook", "headers": {"Authorization": "Bearer secret123"}}
            ]
        }

        validated_data2 = {
            "webhook_subscriptions": [
                {"url": "https://example.com/webhook", "headers": {"Authorization": "Bearer secret123"}}
            ]
        }

        encrypt_webhook_payloads(validated_data1)
        encrypt_webhook_payloads(validated_data2)

        # URLs should be the same (not encrypted)
        assert validated_data1["webhook_subscriptions"][0]["url"] == validated_data2["webhook_subscriptions"][0]["url"]

        # Encrypted headers should be different each time (Fernet includes random IV)
        encrypted1 = validated_data1["webhook_subscriptions"][0]["headers"]["Authorization"]
        encrypted2 = validated_data2["webhook_subscriptions"][0]["headers"]["Authorization"]
        assert encrypted1 != encrypted2

        # But both should decrypt to the same original value
        decrypted1 = self.codec.decrypt(encrypted1.encode("utf-8")).decode("utf-8")
        decrypted2 = self.codec.decrypt(encrypted2.encode("utf-8")).decode("utf-8")
        assert decrypted1 == decrypted2 == "Bearer secret123"
