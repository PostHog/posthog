import pytest

from posthog.hogql.database.models import FieldOrTable, StringDatabaseField, Table, TableNode
from posthog.hogql.errors import ResolutionError


class _FakeTable(Table):
    fields: dict[str, FieldOrTable] = {}

    def to_printed_hogql(self) -> str:
        return "fake"

    def to_printed_clickhouse(self, context) -> str:
        return "fake"


class TestTableNodeStub:
    def _factory(self, calls: list[int], fields=None):
        def factory() -> FieldOrTable:
            calls.append(1)
            return _FakeTable(fields=dict(fields or {"id": StringDatabaseField(name="id")}))

        return factory

    def test_stub_builds_on_first_get_and_caches(self):
        calls: list[int] = []
        node = TableNode(name="t")
        node._table_factory = self._factory(calls)

        first = node.get()
        second = node.get()

        assert isinstance(first, _FakeTable)
        assert first is second  # cached
        assert len(calls) == 1  # factory ran exactly once

    def test_has_table_true_for_stub_without_building(self):
        calls: list[int] = []
        node = TableNode(name="t")
        node._table_factory = self._factory(calls)

        assert node.has_table() is True
        assert node.has_child([]) is True
        assert calls == []  # not built

    def test_catalog_lists_stub_without_building(self):
        calls: list[int] = []
        root = TableNode(name="root")
        child = TableNode(name="warehouse_table")
        child._table_factory = self._factory(calls)
        root.children["warehouse_table"] = child

        assert root.resolve_all_table_names() == ["warehouse_table"]
        assert root.resolve_visible_table_names() == ["warehouse_table"]
        assert calls == []  # listing never forced a build

    def test_hidden_stub_excluded_from_visible_names(self):
        node = TableNode(name="root")
        child = TableNode(name="secret", hidden=True)
        child._table_factory = self._factory([])
        node.children["secret"] = child

        assert node.resolve_all_table_names() == ["secret"]
        assert node.resolve_visible_table_names() == []

    def test_pending_fields_applied_on_build(self):
        node = TableNode(name="t")
        node._table_factory = self._factory([], fields={"id": StringDatabaseField(name="id")})
        reverse = StringDatabaseField(name="reverse_fk")
        node.add_pending_field("reverse_fk", reverse, override=False)

        built = node.get()
        assert isinstance(built, Table)
        assert built.fields["reverse_fk"] is reverse  # contributed by another table, applied on build

    @pytest.mark.parametrize("override,expect_replacement", [(False, False), (True, True)])
    def test_pending_field_override_semantics_on_build(self, override, expect_replacement):
        existing = StringDatabaseField(name="id")
        replacement = StringDatabaseField(name="replacement")
        node = TableNode(name="t")
        node._table_factory = self._factory([], fields={"id": existing})
        node.add_pending_field("id", replacement, override=override)

        built = node.get()
        assert isinstance(built, Table)
        assert built.fields["id"] is (replacement if expect_replacement else existing)

    def test_pending_field_on_already_built_node_applies_directly(self):
        # A node whose table is already materialized (e.g. always-built posthog tables, or a stub that
        # was built earlier in lazy/mixed order) must apply the field now — pending only runs at build.
        built = _FakeTable(fields={"id": StringDatabaseField(name="id")})
        node = TableNode(name="t", table=built)
        reverse = StringDatabaseField(name="reverse_fk")

        node.add_pending_field("reverse_fk", reverse, override=False)

        assert node.table is built
        assert built.fields["reverse_fk"] is reverse
        assert node._pending_fields == []  # not deferred

    @pytest.mark.parametrize("override,expect_replacement", [(False, False), (True, True)])
    def test_pending_field_override_semantics_on_built_node(self, override, expect_replacement):
        existing = StringDatabaseField(name="id")
        replacement = StringDatabaseField(name="replacement")
        built = _FakeTable(fields={"id": existing})
        node = TableNode(name="t", table=built)

        node.add_pending_field("id", replacement, override=override)
        assert built.fields["id"] is (replacement if expect_replacement else existing)

    def test_merge_with_carries_stub_factory_without_building(self):
        # A stub merged on a name collision must keep its factory, not be dropped.
        calls: list[int] = []
        stub = TableNode(name="t")
        stub._table_factory = self._factory(calls)
        target = TableNode(name="t")

        target.merge_with(stub)

        assert target.has_table() is True
        assert calls == []  # merge didn't build
        built = target.get()
        assert isinstance(built, _FakeTable)
        assert len(calls) == 1  # built once, on access

    def test_merge_with_combines_pending_fields(self):
        stub = TableNode(name="t")
        stub._table_factory = self._factory([])
        reverse = StringDatabaseField(name="reverse_fk")
        stub.add_pending_field("reverse_fk", reverse, override=False)
        target = TableNode(name="t")

        target.merge_with(stub)
        built = target.get()

        assert isinstance(built, Table)
        assert built.fields["reverse_fk"] is reverse  # contributed field survived the merge

    def test_merge_with_override_applies_own_pending_to_adopted_table(self):
        # A node carrying deferred fields that adopts an already-built table (override) must apply them
        # to it now — get() only replays pending fields when it builds from a factory.
        own = StringDatabaseField(name="own_fk")
        stub = TableNode(name="t")
        stub._table_factory = self._factory([])
        stub.add_pending_field("own_fk", own, override=False)

        incoming = _FakeTable(fields={"id": StringDatabaseField(name="id")})
        stub.merge_with(TableNode(name="t", table=incoming), table_conflict_mode="override")

        assert stub.table is incoming  # adopted the built table
        assert incoming.fields["own_fk"] is own  # our deferred field applied to it
        assert stub._pending_fields == []

    def test_get_without_table_or_factory_raises(self):
        with pytest.raises(ResolutionError):
            TableNode(name="t").get()
