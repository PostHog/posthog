from posthog.test.base import BaseTest

from posthog.cdp.hog_flow_inputs import INLINE_ENCRYPTED_MARKER, mask_secret_inputs_for_read, resolve_secret_inputs

SCHEMA = [
    {"key": "url", "type": "string", "secret": False},
    {"key": "access_token", "type": "string", "secret": True},
]


class TestHogFlowInputs(BaseTest):
    def _decrypt_token(self, encrypted_item: dict) -> str:
        # Round-trip helper that proves the value was encrypted with the shared Fernet keys.
        from posthog.helpers.encrypted_fields import EncryptedTextField

        return EncryptedTextField().decrypt(encrypted_item["value"][INLINE_ENCRYPTED_MARKER])

    def test_resolves_only_secret_keys(self):
        # Non-secret keys are not touched — caller is expected to validate them separately.
        inputs = {
            "url": {"value": "https://example.com", "order": 0},
            "access_token": {"value": "super-secret", "order": 1},
        }

        result = resolve_secret_inputs(inputs, SCHEMA)

        assert "url" not in result
        assert INLINE_ENCRYPTED_MARKER in result["access_token"]["value"]
        assert result["access_token"]["order"] == 1
        assert '"super-secret"' == self._decrypt_token(result["access_token"])

    def test_strips_bytecode_when_encrypting_plaintext_secret(self):
        inputs = {
            "access_token": {
                "value": "abc",
                "bytecode": ["_H", 1, 32, "abc"],
                "transpiled": {"lang": "ts", "code": "..."},
                "order": 0,
            },
        }

        result = resolve_secret_inputs(inputs, SCHEMA)

        assert "bytecode" not in result["access_token"]
        assert "transpiled" not in result["access_token"]
        assert INLINE_ENCRYPTED_MARKER in result["access_token"]["value"]

    def test_preserves_existing_when_payload_is_placeholder(self):
        # Frontend sends `{"secret": true}` for an untouched secret.
        existing = resolve_secret_inputs({"access_token": {"value": "real-secret"}}, SCHEMA)
        incoming = {"access_token": {"secret": True}}

        result = resolve_secret_inputs(incoming, SCHEMA, existing_inputs=existing)

        assert result["access_token"]["value"] == existing["access_token"]["value"]

    def test_preserves_existing_when_payload_value_is_empty(self):
        # Empty value with no `{"secret": true}` marker should still be treated as a placeholder.
        existing = resolve_secret_inputs({"access_token": {"value": "real-secret"}}, SCHEMA)
        incoming: dict[str, dict] = {"access_token": {}}

        result = resolve_secret_inputs(incoming, SCHEMA, existing_inputs=existing)

        assert result["access_token"]["value"] == existing["access_token"]["value"]

    def test_restores_secret_when_key_omitted_from_payload(self):
        # Workflow editor's test panel strips secrets out of outgoing payloads entirely.
        # The key is missing from `inputs` but `existing_inputs` has it.
        existing = resolve_secret_inputs({"access_token": {"value": "real-secret"}}, SCHEMA)
        incoming: dict[str, dict] = {}  # frontend omitted access_token

        result = resolve_secret_inputs(incoming, SCHEMA, existing_inputs=existing)

        assert result["access_token"]["value"] == existing["access_token"]["value"]

    def test_omits_missing_secret_with_no_prior_value(self):
        # Nothing to restore — the key just stays out of the result.
        result = resolve_secret_inputs({}, SCHEMA, existing_inputs={})
        assert result == {}

    def test_already_encrypted_values_are_kept_verbatim(self):
        # Draft → active re-validation: the stored encrypted wrapper is sent back unchanged.
        first_pass = resolve_secret_inputs({"access_token": {"value": "abc"}}, SCHEMA)

        result = resolve_secret_inputs(first_pass, SCHEMA)

        assert result["access_token"]["value"] == first_pass["access_token"]["value"]

    def test_no_secret_keys_returns_empty_dict(self):
        # Schema has no secret fields → nothing to resolve. Non-secret inputs are not the
        # caller's concern; merge happens at the call site.
        result = resolve_secret_inputs(
            {"url": {"value": "https://example.com"}},
            [{"key": "url", "type": "string"}],
        )
        assert result == {}

    def test_does_not_mutate_caller_inputs(self):
        # The validator hands us request data; mutating it would be a footgun.
        original = {"access_token": {"value": "abc"}}
        original_copy = {"access_token": {"value": "abc"}}

        resolve_secret_inputs(original, SCHEMA)

        assert original == original_copy

    def test_mask_secret_inputs_for_read_replaces_encrypted_with_placeholder(self):
        resolved = resolve_secret_inputs(
            {
                "url": {"value": "https://example.com"},
                "access_token": {"value": "abc"},
            },
            SCHEMA,
        )
        # `resolved` only has secret keys; merge in the non-secret manually to mirror what
        # the validator does before persisting.
        stored = {"url": {"value": "https://example.com"}, **resolved}

        masked = mask_secret_inputs_for_read(stored, SCHEMA)

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
        inputs: dict[str, dict] = {"access_token": {}}
        masked = mask_secret_inputs_for_read(inputs, SCHEMA)
        assert masked["access_token"] == {}
