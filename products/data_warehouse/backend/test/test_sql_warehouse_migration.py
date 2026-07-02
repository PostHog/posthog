"""Source-agnostic warehouse migration: capability detection + qualify-in-place on non-Postgres rows.

Postgres end-to-end lives in `api/test/test_postgres_warehouse_migration.py`.
"""

import uuid
from types import SimpleNamespace
from typing import Any, cast

from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.data_warehouse.backend.sql_warehouse_migration import (
    _source_has_optional_schema_field,
    apply_on_refresh,
    apply_on_schema_clear,
    detect_schema_clear_transition,
    is_multi_schema_capable_sql_source,
    source_namespace_is_blank,
)
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import SQLSource


def _sql_source_stub(*, schema_required: bool | None, has_schema_field: bool = True) -> Any:
    source = MagicMock(spec=SQLSource)
    fields = [SimpleNamespace(name="host", required=True)]
    if has_schema_field:
        fields.append(SimpleNamespace(name="schema", required=schema_required))
    source.get_source_config = SimpleNamespace(fields=fields)
    return source


class TestMultiSchemaCapability:
    @parameterized.expand(
        [
            ("optional schema field", False, True, True),
            ("required schema field", True, True, False),
            ("no schema field", None, False, False),
        ]
    )
    def test_optional_schema_field_introspection(
        self, _name: str, schema_required: bool | None, has_schema_field: bool, expected: bool
    ) -> None:
        source = _sql_source_stub(schema_required=schema_required, has_schema_field=has_schema_field)
        assert _source_has_optional_schema_field(source) is expected

    def test_non_sql_source_is_not_capable(self) -> None:
        assert _source_has_optional_schema_field(object()) is False
        assert _source_has_optional_schema_field(None) is False

    @parameterized.expand(
        [
            # SQL sources with an optional `schema` field qualify legacy rows; unknown sources never do.
            ("postgres", ExternalDataSourceType.POSTGRES, True),
            ("snowflake", ExternalDataSourceType.SNOWFLAKE, True),
            ("redshift", ExternalDataSourceType.REDSHIFT, True),
            ("mssql", ExternalDataSourceType.MSSQL, True),
            ("mysql", ExternalDataSourceType.MYSQL, True),
            ("unknown type", "NotARealSource", False),
        ]
    )
    def test_capability_by_source_type(
        self, _name: str, source_type: ExternalDataSourceType | str, expected: bool
    ) -> None:
        assert is_multi_schema_capable_sql_source(source_type) is expected

    @parameterized.expand(
        [
            ("set", {"schema": "dbo"}, False),
            ("blank", {"schema": ""}, True),
            ("whitespace", {"schema": "   "}, True),
            ("missing", {}, True),
            ("none", None, True),
        ]
    )
    def test_source_namespace_is_blank(self, _name: str, job_inputs: dict[str, Any] | None, expected: bool) -> None:
        assert source_namespace_is_blank(cast(ExternalDataSource, SimpleNamespace(job_inputs=job_inputs))) is expected


class TestDetectSchemaClearTransition:
    @parameterized.expand(
        [
            ("clears to empty string", "public", "", "public"),
            ("clears to whitespace", "public", "   ", "public"),
            ("still set", "public", "analytics", None),
            ("already blank", "", "", None),
        ]
    )
    def test_capable_source_transitions(self, _name: str, existing: str, incoming: str, expected: str | None) -> None:
        result = detect_schema_clear_transition(
            source_type=ExternalDataSourceType.POSTGRES,
            existing_job_inputs={"schema": existing},
            incoming_job_inputs={"schema": incoming},
        )
        assert result == expected

    def test_incoming_without_schema_key_is_no_transition(self) -> None:
        result = detect_schema_clear_transition(
            source_type=ExternalDataSourceType.POSTGRES,
            existing_job_inputs={"schema": "public"},
            incoming_job_inputs={"host": "localhost"},
        )
        assert result is None

    def test_incapable_source_never_transitions(self) -> None:
        result = detect_schema_clear_transition(
            source_type="NotARealSource",
            existing_job_inputs={"schema": "public"},
            incoming_job_inputs={"schema": ""},
        )
        assert result is None


class TestQualifyNonPostgresRows(BaseTest):
    def _source(self, *, schema: str) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="MSSQL",
            created_by=self.user,
            prefix="legacy",
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
            job_inputs={"host": "localhost", "database": "warehouse", "schema": schema},
        )

    def test_apply_on_schema_clear_qualifies_mssql_rows(self) -> None:
        source = self._source(schema="dbo")
        row = ExternalDataSchema.objects.create(
            team_id=self.team.pk, source_id=source.pk, name="users", should_sync=True
        )

        apply_on_schema_clear(source, "dbo")

        row.refresh_from_db()
        assert row.name == "dbo.users"
        # s3_folder_name locks the Delta path to the legacy folder so existing data is preserved.
        assert row.s3_folder_name == "users"
        metadata = row.sync_type_config.get("schema_metadata") or {}
        assert metadata.get("source_schema") == "dbo"
        assert metadata.get("source_table_name") == "users"

    def test_apply_on_refresh_qualifies_using_pinned_metadata(self) -> None:
        # Blank namespace (post-clear): a legacy row pinned to its old schema qualifies on refresh.
        source = self._source(schema="")
        row = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="orders",
            should_sync=True,
            sync_type_config={"schema_metadata": {"source_schema": "sales", "source_table_name": "orders"}},
        )

        substitutions = apply_on_refresh(source=source, team_id=self.team.pk)

        row.refresh_from_db()
        assert row.name == "sales.orders"
        assert substitutions == {"orders": "sales.orders"}
        assert row.s3_folder_name == "orders"

    def test_apply_on_refresh_is_noop_for_already_qualified_rows(self) -> None:
        source = self._source(schema="")
        ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="sales.orders",
            should_sync=True,
            sync_type_config={
                "dwh_storage_key": "orders",
                "schema_metadata": {"source_schema": "sales", "source_table_name": "orders"},
            },
        )

        substitutions = apply_on_refresh(source=source, team_id=self.team.pk)

        assert substitutions == {}
        names = list(
            ExternalDataSchema.objects.filter(team_id=self.team.pk, source_id=source.pk, deleted=False).values_list(
                "name", flat=True
            )
        )
        assert names == ["sales.orders"]

    def test_cross_namespace_duplicate_table_names_stay_distinct(self) -> None:
        # Same table name in two schemas must coexist; refresh must not collapse them.
        source = self._source(schema="")
        for namespace in ("dbo", "sales"):
            ExternalDataSchema.objects.create(
                team_id=self.team.pk,
                source_id=source.pk,
                name=f"{namespace}.users",
                should_sync=True,
                sync_type_config={
                    "dwh_storage_key": f"{namespace}_users",
                    "schema_metadata": {"source_schema": namespace, "source_table_name": "users"},
                },
            )

        substitutions = apply_on_refresh(source=source, team_id=self.team.pk)

        assert substitutions == {}
        names = set(
            ExternalDataSchema.objects.filter(team_id=self.team.pk, source_id=source.pk, deleted=False).values_list(
                "name", flat=True
            )
        )
        assert names == {"dbo.users", "sales.users"}
