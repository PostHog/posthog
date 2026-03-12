from posthog.test.base import BaseTest

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.personal_api_key_service import (
    MAX_API_KEYS_PER_USER,
    create_personal_api_key,
    list_personal_api_keys,
    roll_personal_api_key,
    validate_scopes,
)


class TestPersonalApiKeyService(BaseTest):
    def test_validate_scopes_valid(self):
        result = validate_scopes(["query:read", "insight:write"])
        assert result == ["query:read", "insight:write"]

    def test_validate_scopes_wildcard(self):
        result = validate_scopes(["*"])
        assert result == ["*"]

    def test_validate_scopes_invalid(self):
        with self.assertRaises(ValueError):
            validate_scopes(["invalid"])

    def test_validate_scopes_invalid_object(self):
        with self.assertRaises(ValueError):
            validate_scopes(["nonexistent:read"])

    def test_validate_scopes_invalid_action(self):
        with self.assertRaises(ValueError):
            validate_scopes(["query:nonexistent"])

    def test_create_personal_api_key(self):
        key, value = create_personal_api_key(self.user, "test-label", ["query:read"])
        assert isinstance(key, PersonalAPIKey)
        assert key.label == "test-label"
        assert key.scopes == ["query:read"]
        assert value.startswith("phx_")
        assert key.mask_value.startswith("phx_")
        assert "..." in key.mask_value

    def test_create_personal_api_key_limit(self):
        for i in range(MAX_API_KEYS_PER_USER):
            create_personal_api_key(self.user, f"key-{i}", ["query:read"])

        with self.assertRaises(ValueError):
            create_personal_api_key(self.user, "one-too-many", ["query:read"])

    def test_roll_personal_api_key(self):
        key, original_value = create_personal_api_key(self.user, "roll-test", ["query:read"])
        original_mask = key.mask_value

        key, new_value = roll_personal_api_key(key)
        assert new_value.startswith("phx_")
        assert new_value != original_value
        assert key.mask_value != original_mask
        assert key.last_rolled_at is not None

    def test_list_personal_api_keys(self):
        create_personal_api_key(self.user, "key-a", ["query:read"])
        create_personal_api_key(self.user, "key-b", ["insight:write"])

        keys = list(list_personal_api_keys(self.user))
        assert len(keys) == 2
        labels = {k.label for k in keys}
        assert labels == {"key-a", "key-b"}

    def test_list_personal_api_keys_empty(self):
        keys = list(list_personal_api_keys(self.user))
        assert keys == []

    def test_list_personal_api_keys_ordered_by_created_at_desc(self):
        create_personal_api_key(self.user, "first", ["query:read"])
        create_personal_api_key(self.user, "second", ["query:read"])

        keys = list(list_personal_api_keys(self.user))
        assert keys[0].label == "second"
        assert keys[1].label == "first"
