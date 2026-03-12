from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.command_parser import parse_command
from posthog.hogql.errors import SyntaxError


class TestCommandParser(BaseTest):
    # --- API key commands ---

    @parameterized.expand(
        [
            ("basic", "CREATE API KEY 'my-key' WITH SCOPES 'query:read'", "my-key", ["query:read"]),
            (
                "multiple_scopes",
                "CREATE API KEY 'test' WITH SCOPES 'query:read', 'insight:write'",
                "test",
                ["query:read", "insight:write"],
            ),
            ("case_insensitive", "create api key 'My Key' with scopes 'query:read'", "My Key", ["query:read"]),
            ("trailing_semicolon", "CREATE API KEY 'k' WITH SCOPES 'query:read';", "k", ["query:read"]),
            ("extra_whitespace", "  CREATE  API  KEY  'k'  WITH  SCOPES  'a:b'  ", "k", ["a:b"]),
        ]
    )
    def test_parse_create_api_key(self, _name: str, statement: str, label: str, scopes: list[str]):
        result = parse_command(statement)
        assert isinstance(result, ast.CreateApiKeyCommand)
        assert result.label == label
        assert result.scopes == scopes

    def test_parse_show_api_keys(self):
        result = parse_command("SHOW API KEYS")
        assert isinstance(result, ast.ShowApiKeysCommand)

    def test_parse_show_api_keys_case_insensitive(self):
        result = parse_command("show api keys")
        assert isinstance(result, ast.ShowApiKeysCommand)

    def test_parse_show_api_keys_trailing_semicolon(self):
        result = parse_command("SHOW API KEYS;")
        assert isinstance(result, ast.ShowApiKeysCommand)

    @parameterized.expand(
        [
            ("basic", "ALTER API KEY 'my-key' ROLL", "my-key"),
            ("case_insensitive", "alter api key 'My Key' roll", "My Key"),
            ("trailing_semicolon", "ALTER API KEY 'k' ROLL;", "k"),
        ]
    )
    def test_parse_alter_api_key_roll(self, _name: str, statement: str, label: str):
        result = parse_command(statement)
        assert isinstance(result, ast.AlterApiKeyRollCommand)
        assert result.label == label

    def test_not_a_command(self):
        with self.assertRaises(SyntaxError):
            parse_command("SELECT 1")

    def test_invalid_create_syntax(self):
        with self.assertRaises(SyntaxError):
            parse_command("CREATE API KEY")

    def test_create_no_scopes(self):
        with self.assertRaises(SyntaxError):
            parse_command("CREATE API KEY 'test' WITH SCOPES")

    # --- GRANT commands ---

    @parameterized.expand(
        [
            (
                "grant_to_role",
                "GRANT editor ON insight TO ROLE 'Data Analyst'",
                "editor",
                "insight",
                None,
                "role",
                "Data Analyst",
            ),
            (
                "grant_to_user",
                "GRANT viewer ON dashboard TO USER 'user@example.com'",
                "viewer",
                "dashboard",
                None,
                "user",
                "user@example.com",
            ),
            (
                "grant_to_default",
                "GRANT editor ON insight TO DEFAULT",
                "editor",
                "insight",
                None,
                "default",
                None,
            ),
            (
                "grant_with_resource_name",
                "GRANT manager ON insight 'abc-123' TO ROLE 'Admins'",
                "manager",
                "insight",
                "abc-123",
                "role",
                "Admins",
            ),
            (
                "grant_case_insensitive",
                "grant Editor on Dashboard to role 'My Role'",
                "editor",
                "dashboard",
                None,
                "role",
                "My Role",
            ),
            (
                "grant_trailing_semicolon",
                "GRANT viewer ON insight TO DEFAULT;",
                "viewer",
                "insight",
                None,
                "default",
                None,
            ),
        ]
    )
    def test_parse_grant(self, _name, statement, level, resource, resource_name, target_type, target_name):
        result = parse_command(statement)
        assert isinstance(result, ast.GrantCommand)
        assert result.access_level == level
        assert result.resource == resource
        assert result.resource_name == resource_name
        assert result.target_type == target_type
        assert result.target_name == target_name

    def test_invalid_grant_syntax(self):
        with self.assertRaises(SyntaxError):
            parse_command("GRANT ON insight TO ROLE 'test'")

    # --- REVOKE commands ---

    @parameterized.expand(
        [
            (
                "revoke_from_role",
                "REVOKE ON insight FROM ROLE 'Data Analyst'",
                "insight",
                None,
                "role",
                "Data Analyst",
            ),
            (
                "revoke_from_user",
                "REVOKE ON dashboard FROM USER 'user@example.com'",
                "dashboard",
                None,
                "user",
                "user@example.com",
            ),
            (
                "revoke_from_default",
                "REVOKE ON insight FROM DEFAULT",
                "insight",
                None,
                "default",
                None,
            ),
            (
                "revoke_with_resource_name",
                "REVOKE ON insight 'abc-123' FROM ROLE 'Admins'",
                "insight",
                "abc-123",
                "role",
                "Admins",
            ),
        ]
    )
    def test_parse_revoke(self, _name, statement, resource, resource_name, target_type, target_name):
        result = parse_command(statement)
        assert isinstance(result, ast.RevokeCommand)
        assert result.resource == resource
        assert result.resource_name == resource_name
        assert result.target_type == target_type
        assert result.target_name == target_name

    def test_invalid_revoke_syntax(self):
        with self.assertRaises(SyntaxError):
            parse_command("REVOKE insight FROM ROLE 'test'")

    # --- SHOW GRANTS commands ---

    @parameterized.expand(
        [
            ("bare", "SHOW GRANTS", None, None, None, None),
            ("on_resource", "SHOW GRANTS ON insight", "insight", None, None, None),
            ("on_resource_with_name", "SHOW GRANTS ON insight 'abc-123'", "insight", "abc-123", None, None),
            ("for_role", "SHOW GRANTS FOR ROLE 'Data Analyst'", None, None, "role", "Data Analyst"),
            ("for_user", "SHOW GRANTS FOR USER 'user@example.com'", None, None, "user", "user@example.com"),
            (
                "on_resource_for_role",
                "SHOW GRANTS ON insight FOR ROLE 'Admins'",
                "insight",
                None,
                "role",
                "Admins",
            ),
        ]
    )
    def test_parse_show_grants(self, _name, statement, resource, resource_name, filter_type, filter_name):
        result = parse_command(statement)
        assert isinstance(result, ast.ShowGrantsCommand)
        assert result.resource == resource
        assert result.resource_name == resource_name
        assert result.filter_type == filter_type
        assert result.filter_name == filter_name
