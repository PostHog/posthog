from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.command_parser import parse_command
from posthog.hogql.errors import SyntaxError


class TestCommandParser(BaseTest):
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
