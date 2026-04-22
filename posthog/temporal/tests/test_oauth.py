from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.temporal.oauth import INTERNAL_SCOPES, MCP_READ_SCOPES, MCP_WRITE_SCOPES, has_write_scopes, resolve_scopes


class TestResolveScopes(SimpleTestCase):
    def test_read_only_preset(self) -> None:
        result = resolve_scopes("read_only")
        assert set(result) == set(MCP_READ_SCOPES + INTERNAL_SCOPES)
        assert "action:write" not in result

    def test_read_only_is_default(self) -> None:
        assert resolve_scopes() == resolve_scopes("read_only")

    def test_full_preset(self) -> None:
        result = resolve_scopes("full")
        assert set(result) == set(MCP_READ_SCOPES + MCP_WRITE_SCOPES + INTERNAL_SCOPES)

    def test_custom_scopes(self) -> None:
        custom = ["feature_flag:read", "feature_flag:write"]
        result = resolve_scopes(custom)
        assert set(result) == set(custom + INTERNAL_SCOPES)

    def test_internal_scopes_always_included(self) -> None:
        for scope in INTERNAL_SCOPES:
            assert scope in resolve_scopes("read_only")
            assert scope in resolve_scopes("full")
            assert scope in resolve_scopes(["feature_flag:read"])


class TestHasWriteScopes(SimpleTestCase):
    @parameterized.expand(
        [
            ("read_only_preset", "read_only", False),
            ("full_preset", "full", True),
            ("custom_with_mcp_write", ["feature_flag:read", "feature_flag:write"], True),
            ("custom_read_only", ["feature_flag:read", "insight:read"], False),
            ("custom_with_non_mcp_write", ["task:write"], False),
            ("empty_custom", [], False),
        ]
    )
    def test_has_write_scopes(self, _name: str, scopes, expected: bool) -> None:
        assert has_write_scopes(scopes) == expected
