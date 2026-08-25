from unittest.mock import MagicMock

from django.test import SimpleTestCase

from parameterized import parameterized

from products.customer_analytics.backend.presentation.views.views import _WarehouseScopeGatedAccessControl


class _Meta:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name


class _FakeModel:
    def __init__(self, model_name: str) -> None:
        self._meta = _Meta(model_name)


class TestWarehouseScopeGatedAccessControl(SimpleTestCase):
    def _gate(self, scopes: list[str]) -> tuple[_WarehouseScopeGatedAccessControl, MagicMock]:
        inner = MagicMock()
        inner.check_access_level_for_object.return_value = True
        return _WarehouseScopeGatedAccessControl(inner, scopes), inner

    @parameterized.expand(
        [
            # (model name, token scopes, required level, allowed?)
            ("table_no_warehouse_scope_editor", "externaldatasource", ["account:write"], "editor", False),
            ("table_no_warehouse_scope_viewer", "externaldatasource", ["account:read"], "viewer", False),
            ("table_read_covers_viewer", "externaldatasource", ["external_data_source:read"], "viewer", True),
            ("table_read_not_editor", "externaldatasource", ["external_data_source:read"], "editor", False),
            ("table_write_covers_editor", "externaldatasource", ["external_data_source:write"], "editor", True),
            ("table_write_covers_viewer", "externaldatasource", ["external_data_source:write"], "viewer", True),
            ("table_wildcard_allows", "externaldatasource", ["*"], "editor", True),
            # A view binding gates on warehouse_view — the table's scope doesn't cover it, or vice versa.
            ("view_no_warehouse_scope_editor", "datawarehousesavedquery", ["account:write"], "editor", False),
            ("view_no_warehouse_scope_viewer", "datawarehousesavedquery", ["account:read"], "viewer", False),
            ("view_read_covers_viewer", "datawarehousesavedquery", ["warehouse_view:read"], "viewer", True),
            ("view_read_not_editor", "datawarehousesavedquery", ["warehouse_view:read"], "editor", False),
            ("view_write_covers_editor", "datawarehousesavedquery", ["warehouse_view:write"], "editor", True),
            ("view_write_covers_viewer", "datawarehousesavedquery", ["warehouse_view:write"], "viewer", True),
            ("view_wildcard_allows", "datawarehousesavedquery", ["*"], "editor", True),
            (
                "view_not_covered_by_table_scope",
                "datawarehousesavedquery",
                ["external_data_source:write"],
                "editor",
                False,
            ),
            ("table_not_covered_by_view_scope", "externaldatasource", ["warehouse_view:write"], "editor", False),
        ]
    )
    def test_warehouse_object_gated_on_token_scope(self, _name, model_name, scopes, level, allowed):
        gate, inner = self._gate(scopes)
        result = gate.check_access_level_for_object(_FakeModel(model_name), required_level=level)
        assert result is allowed
        # When the token scope denies, the wrapped RBAC check is never consulted (fail closed on scope).
        if not allowed:
            inner.check_access_level_for_object.assert_not_called()

    def test_non_warehouse_object_delegates(self):
        # A different resource is unaffected by the warehouse scope gate — it delegates to the RBAC check.
        gate, inner = self._gate(["account:write"])
        assert gate.check_access_level_for_object(_FakeModel("dashboard"), required_level="editor") is True
        inner.check_access_level_for_object.assert_called_once()
