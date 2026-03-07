from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.commands import execute_command
from posthog.hogql.errors import QueryError

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.personal_api_key_service import create_personal_api_key


class TestCommandExecutor(BaseTest):
    def test_create_api_key(self):
        node = ast.CreateApiKeyCommand(label="test-key", scopes=["query:read"])
        response = execute_command(node, self.user)

        assert response.columns == ["api_key", "label", "scopes", "created_at"]
        assert len(response.results) == 1
        row = response.results[0]
        assert row[0].startswith("phx_")
        assert row[1] == "test-key"
        assert row[2] == ["query:read"]

        key = PersonalAPIKey.objects.get(user=self.user, label="test-key")
        assert key is not None

    def test_create_api_key_invalid_scope(self):
        node = ast.CreateApiKeyCommand(label="bad-key", scopes=["invalid:scope"])
        with self.assertRaises(QueryError):
            execute_command(node, self.user)

    def test_show_api_keys(self):
        create_personal_api_key(self.user, "key-1", ["query:read"])
        create_personal_api_key(self.user, "key-2", ["insight:write"])

        node = ast.ShowApiKeysCommand()
        response = execute_command(node, self.user)

        assert response.columns == [
            "id",
            "label",
            "mask_value",
            "scopes",
            "created_at",
            "last_used_at",
            "last_rolled_at",
        ]
        assert len(response.results) == 2
        labels = {row[1] for row in response.results}
        assert labels == {"key-1", "key-2"}

    def test_show_api_keys_empty(self):
        node = ast.ShowApiKeysCommand()
        response = execute_command(node, self.user)
        assert response.results == []

    def test_alter_api_key_roll(self):
        key, original_value = create_personal_api_key(self.user, "roll-me", ["query:read"])

        node = ast.AlterApiKeyRollCommand(label="roll-me")
        response = execute_command(node, self.user)

        assert response.columns == ["api_key", "label", "last_rolled_at"]
        assert len(response.results) == 1
        new_value = response.results[0][0]
        assert new_value.startswith("phx_")
        assert new_value != original_value

    def test_alter_api_key_roll_not_found(self):
        node = ast.AlterApiKeyRollCommand(label="nonexistent")
        with self.assertRaises(QueryError):
            execute_command(node, self.user)

    def test_create_api_key_limit(self):
        for i in range(10):
            create_personal_api_key(self.user, f"key-{i}", ["query:read"])

        node = ast.CreateApiKeyCommand(label="too-many", scopes=["query:read"])
        with self.assertRaises(QueryError):
            execute_command(node, self.user)
