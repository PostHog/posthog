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
            # (token scopes, required level, allowed?)
            ("no_warehouse_scope_editor", ["account:write"], "editor", False),
            ("no_warehouse_scope_viewer", ["account:read"], "viewer", False),
            ("read_scope_covers_viewer", ["external_data_source:read"], "viewer", True),
            ("read_scope_not_editor", ["external_data_source:read"], "editor", False),
            ("write_scope_covers_editor", ["external_data_source:write"], "editor", True),
            ("write_scope_covers_viewer", ["external_data_source:write"], "viewer", True),
            ("wildcard_allows", ["*"], "editor", True),
        ]
    )
    def test_external_data_source_object_gated_on_token_scope(self, _name, scopes, level, allowed):
        gate, inner = self._gate(scopes)
        result = gate.check_access_level_for_object(_FakeModel("externaldatasource"), required_level=level)
        assert result is allowed
        # When the token scope denies, the wrapped RBAC check is never consulted (fail closed on scope).
        if not allowed:
            inner.check_access_level_for_object.assert_not_called()

    def test_non_warehouse_object_delegates(self):
        # A different resource is unaffected by the warehouse scope gate — it delegates to the RBAC check.
        gate, inner = self._gate(["account:write"])
        assert gate.check_access_level_for_object(_FakeModel("dashboard"), required_level="editor") is True
        inner.check_access_level_for_object.assert_called_once()
