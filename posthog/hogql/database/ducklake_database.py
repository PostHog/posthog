from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from posthog.schema import (
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaSchema,
    DatabaseSchemaSource,
    HogQLQueryModifiers,
)

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database, serialize_fields
from posthog.hogql.database.direct_ducklake_table import DirectDuckLakeTable
from posthog.hogql.database.models import TableNode
from posthog.hogql.timings import HogQLTimings

from posthog.ducklake.schema import DuckLakeSchemaTable, get_cached_ducklake_schema

from products.data_warehouse.backend.models.util import STR_TO_HOGQL_MAPPING, postgres_columns_to_dwh_columns

if TYPE_CHECKING:
    from posthog.models import Team, User


def _ducklake_columns_to_fields(
    db_columns: dict[str, dict[str, str | bool]],
) -> dict[str, object]:
    fields: dict[str, object] = {}
    default_field = STR_TO_HOGQL_MAPPING["UnknownDatabaseField"]

    for column_name, column in db_columns.items():
        hogql_type = str(column.get("hogql", "UnknownDatabaseField"))
        clickhouse_type = str(column.get("clickhouse", ""))
        field = STR_TO_HOGQL_MAPPING.get(hogql_type, default_field)(
            name=column_name,
            nullable=clickhouse_type.startswith("Nullable("),
        )
        fields[column_name] = field

    return fields


class DuckLakeDatabase(Database):
    def __init__(self, timezone: str | None = None, week_start_day=None):
        super().__init__(timezone=timezone, week_start_day=week_start_day)
        self.tables = TableNode(children={})
        self._ducklake_tables: dict[str, DuckLakeSchemaTable] = {}

    @classmethod
    def create_for(
        cls,
        team_id: int | None = None,
        *,
        team: Optional[Team] = None,
        user: Optional[User] = None,
        modifiers: HogQLQueryModifiers | None = None,
        timings: HogQLTimings | None = None,
        connection_id: str | None = None,
    ) -> DuckLakeDatabase:
        del user, modifiers, connection_id

        if team is None and team_id is None:
            raise ValueError("Either team_id or team must be provided")
        if team is None:
            from posthog.models import Team

            team = Team.objects.get(pk=team_id)

        if timings is None:
            timings = HogQLTimings()

        database = cls(timezone=team.timezone, week_start_day=team.week_start_day)
        database._connection_id = "ducklake://default"

        with timings.measure("ducklake_schema"):
            schema_tables = get_cached_ducklake_schema(team.pk)

        for schema_table in schema_tables:
            qualified_name = schema_table.qualified_name
            db_columns = postgres_columns_to_dwh_columns(schema_table.columns)
            fields = _ducklake_columns_to_fields(db_columns)
            table = DirectDuckLakeTable(
                name=qualified_name,
                fields=fields,
                postgres_schema=schema_table.schema_name,
                postgres_table_name=schema_table.table_name,
                external_data_source_id="ducklake://default",
            )
            database.tables.add_child(
                TableNode.create_nested_for_chain([schema_table.schema_name, schema_table.table_name], table)
            )
            database._ducklake_tables[qualified_name] = schema_table
            database._warehouse_table_names.append(qualified_name)

        return database

    def get_posthog_table_names(self, include_hidden: bool = False) -> list[str]:
        del include_hidden
        return []

    def get_system_table_names(self) -> list[str]:
        return []

    def get_view_names(self) -> list[str]:
        return []

    def serialize(
        self,
        context: HogQLContext,
        include_only: set[str] | None = None,
        include_hidden_posthog_tables: bool = False,
    ) -> dict[str, DatabaseSchemaDataWarehouseTable]:
        del include_hidden_posthog_tables

        source = DatabaseSchemaSource(
            id="ducklake://default",
            status="Completed",
            source_type="Ducklake",
            access_method="direct",
            prefix="ducklake",
        )

        tables: dict[str, DatabaseSchemaDataWarehouseTable] = {}
        for qualified_name, schema_table in self._ducklake_tables.items():
            if include_only and qualified_name not in include_only:
                continue

            table = self.get_table(qualified_name)
            db_columns = postgres_columns_to_dwh_columns(schema_table.columns)
            fields = serialize_fields(
                table.fields, context, qualified_name.split("."), db_columns, table_type="external"
            )
            tables[qualified_name] = DatabaseSchemaDataWarehouseTable(
                fields={field.name: field for field in fields},
                id=f"ducklake:{qualified_name}",
                name=qualified_name,
                format="DuckLake",
                url_pattern=f"ducklake://{qualified_name}",
                schema=DatabaseSchemaSchema(
                    id=f"ducklake:{qualified_name}",
                    name=qualified_name,
                    should_sync=True,
                    incremental=False,
                ),
                source=source,
            )

        return tables
