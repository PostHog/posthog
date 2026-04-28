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

    def test_include_internal_scopes_false_drops_internal_scopes(self) -> None:
        custom = ["clickhouse_test_cluster_perf:read"]
        result = resolve_scopes(custom, include_internal_scopes=False)
        assert result == custom
        for scope in INTERNAL_SCOPES:
            assert scope not in result

    def test_include_internal_scopes_false_for_read_only_preset(self) -> None:
        result = resolve_scopes("read_only", include_internal_scopes=False)
        assert set(result) == set(MCP_READ_SCOPES)
        for scope in INTERNAL_SCOPES:
            assert scope not in result

    def test_internal_scope_objects_disjoint_from_mcp_scope_lists(self) -> None:
        from posthog.scopes import INTERNAL_API_SCOPE_OBJECTS

        mcp_scope_objects: set[str] = {scope.split(":", 1)[0] for scope in [*MCP_READ_SCOPES, *MCP_WRITE_SCOPES]}
        internal: set[str] = set(INTERNAL_API_SCOPE_OBJECTS)
        overlap = internal & mcp_scope_objects
        assert overlap == set(), (
            f"{overlap} are in INTERNAL_API_SCOPE_OBJECTS and also in MCP_READ_SCOPES / MCP_WRITE_SCOPES; "
            "a `read_only` MCP token would silently grant them."
        )


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
