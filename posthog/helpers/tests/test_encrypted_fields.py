import json

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from cryptography.fernet import InvalidToken

from posthog.helpers.encrypted_fields import EncryptedFieldMixin, EncryptedJSONField


class TestEncryptedFields(BaseTest):
    def test_simple_encryption_and_decryption(self):
        """
        Simple test case to be replicated in node tests or anywhere else that the same secrets will be used
        """
        ef = EncryptedFieldMixin()
        with freeze_time("2024-01-01T00:01:00Z"):
            with patch("os.urandom", return_value=b"\x00" * 16):
                encrypted = ef.f.encrypt(bytes("test-case", "utf-8")).decode("utf-8")

        assert (
            encrypted
            == "gAAAAABlkgC8AAAAAAAAAAAAAAAAAAAAAP89mTGU6xUyLcVUIB4ySnX2Y8ZgwLALpzYGfm76Fk64vPRY62flSIigMa_MqTlKyA=="
        )
        decrypted = ef.f.decrypt(bytes(encrypted, "utf-8")).decode("utf-8")

        assert decrypted == "test-case"

    def test_encrypted_json_field_raises_on_undecryptable_value(self):
        """A nested ciphertext that cannot be decrypted must raise instead of silently
        passing the encrypted blob through to consumers (which previously crashed
        downstream parsers with `ValueError: invalid literal for int()`)."""

        field = EncryptedJSONField()
        # Build a value where one nested string is encrypted under a *different* key,
        # so it will not be decryptable with the current `field.f`.
        valid_token = field.encrypt("443")
        # A Fernet token with a different MAC — guaranteed to not decrypt under our keys.
        bad_token = (
            "gAAAAABlkgC8AAAAAAAAAAAAAAAAAAAAAP89mTGU6xUyLcVUIB4ySnX2Y8ZgwLALpzYGfm76Fk64vPRY62flSIigMa_MqTlKyA=="
        )
        raw = json.dumps({"port": valid_token, "secret": bad_token})

        with pytest.raises(InvalidToken):
            field.to_python(raw)

    def test_encrypted_json_field_ignore_decrypt_errors_returns_value(self):
        """`ignore_decrypt_errors=True` keeps the legacy soft-fail behavior."""

        field = EncryptedJSONField(ignore_decrypt_errors=True)
        bad_token = (
            "gAAAAABlkgC8AAAAAAAAAAAAAAAAAAAAAP89mTGU6xUyLcVUIB4ySnX2Y8ZgwLALpzYGfm76Fk64vPRY62flSIigMa_MqTlKyA=="
        )
        raw = json.dumps({"k": bad_token})

        result = field.to_python(raw)

        # With `ignore_decrypt_errors=True` we do not raise; the un-decryptable
        # value is returned as-is (no plaintext available).
        assert result == {"k": bad_token}

    def test_simple_field_to_python_passes_plaintext_through(self):
        """Django invokes `to_python` on plaintext during default/save prep — that path
        must not attempt decryption (which would fail since it's not a Fernet token)."""
        from posthog.helpers.encrypted_fields import EncryptedTextField

        field = EncryptedTextField()
        # Plain text input should pass through without raising.
        assert field.to_python("hello world") == "hello world"
        assert field.to_python("") == ""

    def test_simple_field_to_python_decrypts_fernet_input(self):
        from posthog.helpers.encrypted_fields import EncryptedTextField

        field = EncryptedTextField()
        encrypted = field.encrypt("secret-value")
        assert field.to_python(encrypted) == "secret-value"

    def test_encrypted_json_field_to_python_passes_plaintext_through(self):
        """Plaintext JSON (e.g. defaults like `{}` or form input) must pass through
        even though it contains values that aren't Fernet tokens."""
        field = EncryptedJSONField()

        assert field.to_python(json.dumps({})) == {}
        assert field.to_python(json.dumps({"key": "plaintext"})) == {"key": "plaintext"}
        assert field.to_python(json.dumps({"port": 5432, "host": "localhost"})) == {
            "port": 5432,
            "host": "localhost",
        }

    def test_encrypted_json_field_to_python_round_trips_encrypted_values(self):
        """Encrypted values written via `_encrypt_values` round-trip back to plaintext."""
        field = EncryptedJSONField()
        plaintext = {"port": "5432", "host": "db.example.com"}
        # Simulate the save → load round trip.
        encoded = field.get_prep_value(plaintext)
        result = field.to_python(encoded)

        assert result == plaintext
