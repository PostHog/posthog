from typing import Literal

from pydantic import BaseModel

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database

from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from ee.hogai.external_tool import ExternalTool, ExternalToolResult, register_external_tool


class ReadDataWarehouseSchemaQuery(BaseModel):
    kind: Literal["data_warehouse_schema"] = "data_warehouse_schema"


class ReadDataWarehouseSchemaExternalToolArgs(BaseModel):
    query: ReadDataWarehouseSchemaQuery


@register_external_tool
class ReadDataWarehouseSchemaExternalTool(ExternalTool):
    """
    External tool that returns core PostHog table schemas (events, groups, persons, sessions).

    This provides the data model information needed for writing HogQL queries.
    """

    name = "read_data_warehouse_schema"
    args_schema = ReadDataWarehouseSchemaExternalToolArgs

    async def execute(self, team: Team, user: User, **args) -> ExternalToolResult:
        try:
            result = await self._build_tables_list(team)
            return ExternalToolResult(
                success=True,
                content=result,
                data={"tables": ["events", "groups", "persons", "sessions"]},
            )
        except Exception as e:
            return ExternalToolResult(
                success=False,
                content=f"Failed to read data warehouse schema: {e}",
                error="execution_error",
            )

    @database_sync_to_async(thread_sensitive=False)
    def _build_tables_list(self, team: Team) -> str:
        database = Database.create_for(team=team)
        hogql_context = HogQLContext(
            team=team,
            enable_select_queries=True,
            database=database,
        )

        core_tables = {"events", "groups", "persons", "sessions"}
        serialized = database.serialize(hogql_context, include_only=core_tables)

        lines: list[str] = ["# Core PostHog tables", ""]

        for table_name, table in serialized.items():
            lines.append(f"## Table `{table_name}`")
            for field in table.fields.values():
                lines.append(f"- {field.name} ({field.type})")
            lines.append("")

        # Add warehouse tables, system tables, and views (names only)
        warehouse_tables = database.get_warehouse_table_names()
        system_tables = database.get_system_table_names()
        views = database.get_view_names()

        def listify(items: list[str]) -> str:
            return "\n".join(f"- {item}" for item in sorted(items))

        def section(title: str, items: list[str]) -> str:
            return f"# {title}\n{listify(items)}\n" if items else ""

        extra_sections = (
            f"{section('Data warehouse tables', warehouse_tables)}"
            f"{section('PostHog Postgres tables', system_tables)}"
            f"{section('Data warehouse views', views)}"
        )

        return "\n".join(lines) + extra_sections
