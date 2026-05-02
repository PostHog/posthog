from __future__ import annotations

from unittest import TestCase

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.managed_warehouse_postgres_table import ManagedWarehousePostgresTable


class TestManagedWarehousePostgresTable(TestCase):
    def _build_table(self, **overrides) -> ManagedWarehousePostgresTable:
        defaults: dict = {
            "name": "public.users",
            "fields": {},
            "host": "duckgres.example.com",
            "port": 5432,
            "database": "ducklake",
            "user": "warehouse_user",
            "password": "s3cret",
            "schema": "public",
            "postgres_table_name": "users",
        }
        defaults.update(overrides)
        return ManagedWarehousePostgresTable(**defaults)

    def test_emits_postgresql_call_with_parameter_placeholders(self):
        context = HogQLContext(team_id=1)
        table = self._build_table()

        rendered = table.to_printed_clickhouse(context)

        # Six %(...)s placeholders, one per positional postgresql() argument.
        assert rendered.startswith("postgresql(")
        assert rendered.endswith(")")
        assert rendered.count("%(") == 6

    def test_credentials_never_appear_inline_in_rendered_sql(self):
        context = HogQLContext(team_id=1)
        table = self._build_table()

        rendered = table.to_printed_clickhouse(context)

        # None of the actual values should appear as literals — they must all be bound.
        assert "duckgres.example.com" not in rendered
        assert "ducklake" not in rendered
        assert "warehouse_user" not in rendered
        assert "s3cret" not in rendered
        assert "public" not in rendered
        assert "users" not in rendered

    def test_values_are_bound_into_context_in_postgresql_argument_order(self):
        context = HogQLContext(team_id=1)
        table = self._build_table()

        table.to_printed_clickhouse(context)

        # context.add_sensitive_value() returns "%(hogql_val_N_sensitive)s" with N counting up.
        # We expect exactly six bound values, in argument order: address, db, table, user, password, schema.
        sensitive_values = [v for k, v in sorted(context.values.items()) if k.endswith("_sensitive")]
        assert sensitive_values == [
            "duckgres.example.com:5432",
            "ducklake",
            "users",
            "warehouse_user",
            "s3cret",
            "public",
        ]

    def test_address_combines_host_and_port(self):
        context = HogQLContext(team_id=1)
        table = self._build_table(host="10.0.0.5", port=6432)

        table.to_printed_clickhouse(context)

        sensitive_values = [v for k, v in sorted(context.values.items()) if k.endswith("_sensitive")]
        assert sensitive_values[0] == "10.0.0.5:6432"

    def test_quoted_identifier_for_to_printed_hogql(self):
        table = self._build_table(name="weird-name with space")
        # Backticks are HogQL's identifier escape; just confirm it's wrapped.
        rendered = table.to_printed_hogql()
        assert rendered.startswith("`")
        assert rendered.endswith("`")

    def test_to_printed_clickhouse_requires_context(self):
        table = self._build_table()
        try:
            table.to_printed_clickhouse(None)  # type: ignore[arg-type]
        except ValueError as exc:
            assert "HogQLContext" in str(exc)
        else:
            raise AssertionError("Expected ValueError when context is None")
