from parameterized import parameterized

from products.data_warehouse.backend.direct_postgres import (
    filter_columns_by_synced_columns,
    filter_dwh_columns_by_synced_columns,
    get_direct_postgres_location,
)


class TestGetDirectPostgresLocation:
    @parameterized.expand(
        [
            ("whitespace_only_schema", "public.accounts", "   ", (None, "public", "accounts")),
            ("trimmed_schema", "accounts", " public ", (None, "public", "accounts")),
        ]
    )
    def test_normalizes_default_schema_before_inference(
        self, _name: str, schema_name: str, default_schema: str, expected: tuple[str | None, str, str]
    ) -> None:
        assert get_direct_postgres_location(schema_name=schema_name, default_schema=default_schema) == expected


class TestFilterColumnsBySyncedColumns:
    columns = [("id", "integer", False), ("email", "text", True), ("name", "text", True), ("secret", "text", True)]

    def test_none_returns_all(self) -> None:
        assert filter_columns_by_synced_columns(self.columns, None, ["id"]) == self.columns

    def test_empty_returns_all(self) -> None:
        assert filter_columns_by_synced_columns(self.columns, [], ["id"]) == self.columns

    def test_subset_excludes_unselected(self) -> None:
        result = filter_columns_by_synced_columns(self.columns, ["email"], ["id"])
        names = [name for name, _type, _nullable in result]
        # PK retained, secret excluded, source order preserved.
        assert names == ["id", "email"]

    def test_incremental_field_retained(self) -> None:
        result = filter_columns_by_synced_columns(self.columns, ["email"], ["id"], incremental_field="name")
        names = [name for name, _type, _nullable in result]
        assert "name" in names

    def test_unknown_synced_column_silently_dropped(self) -> None:
        # Validation lives at the API boundary; helper just intersects with available columns.
        result = filter_columns_by_synced_columns(self.columns, ["email", "ghost"], ["id"])
        names = [name for name, _type, _nullable in result]
        assert names == ["id", "email"]


class TestFilterDwhColumnsBySyncedColumns:
    dwh_columns = {
        "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64"},
        "email": {"hogql": "StringDatabaseField", "clickhouse": "String"},
        "secret": {"hogql": "StringDatabaseField", "clickhouse": "String"},
    }

    def test_none_returns_all(self) -> None:
        assert filter_dwh_columns_by_synced_columns(self.dwh_columns, None, ["id"]) == self.dwh_columns

    def test_subset_keeps_pks(self) -> None:
        result = filter_dwh_columns_by_synced_columns(self.dwh_columns, ["email"], ["id"])
        assert set(result.keys()) == {"id", "email"}
