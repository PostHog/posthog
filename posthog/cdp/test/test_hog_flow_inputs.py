from posthog.test.base import BaseTest

from posthog.cdp.hog_flow_inputs import INLINE_ENCRYPTED_MARKER, encrypt_secret_inputs, mask_secret_inputs_for_read

SCHEMA = [
    {"key": "url", "type": "string", "secret": False},
    {"key": "access_token", "type": "string", "secret": True},
]


class TestHogFlowInputs(BaseTest):
    def _decrypt_token(self, encrypted_item: dict) -> str:
        # Round-trip helper that proves the value was encrypted with the shared Fernet keys.
        from posthog.helpers.encrypted_fields import EncryptedTextField

        return EncryptedTextField().decrypt(encrypted_item["value"][INLINE_ENCRYPTED_MARKER])

    def test_encrypts_secret_values_and_leaves_other_inputs_alone(self):
        inputs = {
            "url": {"value": "https://example.com", "order": 0},
            "access_token": {"value": "super-secret", "order": 1},
        }

        result = encrypt_secret_inputs(inputs, SCHEMA)

        assert result["url"] == {"value": "https://example.com", "order": 0}
        assert INLINE_ENCRYPTED_MARKER in result["access_token"]["value"]
        assert result["access_token"]["order"] == 1
        assert '"super-secret"' == self._decrypt_token(result["access_token"])

    def test_strips_bytecode_from_secret_items(self):
        inputs = {
            "access_token": {
                "value": "abc",
                "bytecode": ["_H", 1, 32, "abc"],
                "transpiled": {"lang": "ts", "code": "..."},
                "order": 0,
            },
        }

        result = encrypt_secret_inputs(inputs, SCHEMA)

        assert "bytecode" not in result["access_token"]
        assert "transpiled" not in result["access_token"]
        assert INLINE_ENCRYPTED_MARKER in result["access_token"]["value"]

    def test_preserves_existing_encrypted_value_when_payload_is_placeholder(self):
        # Encrypt once to produce a realistic stored value.
        first_pass = encrypt_secret_inputs(
            {"access_token": {"value": "real-secret"}},
            SCHEMA,
        )

        # Frontend sends `{"secret": true}` (with no value) when the user didn't touch the field.
        # Empty incoming value should fall back to the stored encrypted value, not wipe it.
        incoming = {"access_token": {}}

        result = encrypt_secret_inputs(incoming, SCHEMA, existing_inputs=first_pass)

        assert result["access_token"]["value"] == first_pass["access_token"]["value"]

    def test_already_encrypted_values_are_left_untouched(self):
        first_pass = encrypt_secret_inputs({"access_token": {"value": "abc"}}, SCHEMA)
        # Simulate a round-trip where the payload still carries the encrypted dict.
        result = encrypt_secret_inputs(first_pass, SCHEMA)
        assert result["access_token"]["value"] == first_pass["access_token"]["value"]

    def test_no_secret_keys_passes_inputs_through(self):
        inputs = {"url": {"value": "https://example.com"}}
        result = encrypt_secret_inputs(inputs, [{"key": "url", "type": "string"}])
        assert result == inputs

    def test_mask_secret_inputs_for_read_replaces_encrypted_with_placeholder(self):
        encrypted = encrypt_secret_inputs(
            {
                "url": {"value": "https://example.com"},
                "access_token": {"value": "abc"},
            },
            SCHEMA,
        )

        masked = mask_secret_inputs_for_read(encrypted, SCHEMA)

        assert masked["url"] == {"value": "https://example.com"}
        assert masked["access_token"] == {"secret": True}

    def test_mask_secret_inputs_for_read_also_masks_legacy_plaintext_secrets(self):
        # Defensive: if a row somehow has plaintext for a secret-schema field (legacy data, bug,
        # mid-migration), the API must still mask it so plaintext doesn't leak to the client.
        inputs = {"access_token": {"value": "cleartext-leftover"}}
        masked = mask_secret_inputs_for_read(inputs, SCHEMA)
        assert masked["access_token"] == {"secret": True}

    def test_mask_secret_inputs_for_read_leaves_empty_secret_alone(self):
        # No value stored — frontend doesn't need a `{secret: true}` placeholder either.
        inputs = {"access_token": {}}
        masked = mask_secret_inputs_for_read(inputs, SCHEMA)
        assert masked["access_token"] == {}
