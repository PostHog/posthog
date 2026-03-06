from typing import Literal

from pydantic import BaseModel

from posthog.sync import database_sync_to_async

from ee.hogai.chat_agent.sql.mixins import HogQLDatabaseMixin
from ee.hogai.mcp_tool import MCPTool, mcp_tool_registry


class ReadDataWarehouseSchemaQuery(BaseModel):
    kind: Literal["data_warehouse_schema"] = "data_warehouse_schema"


class ReadDataWarehouseSchemaMCPToolArgs(BaseModel):
    query: ReadDataWarehouseSchemaQuery


@mcp_tool_registry.register(scopes=["warehouse_table:read", "warehouse_view:read"])
class ReadDataWarehouseSchemaMCPTool(HogQLDatabaseMixin, MCPTool[ReadDataWarehouseSchemaMCPToolArgs]):
    """
    MCP tool that returns core PostHog table schemas (events, groups, persons, sessions).

    This provides the data model information needed for writing HogQL queries.
    """

    name = "read_data_warehouse_schema"
    args_schema = ReadDataWarehouseSchemaMCPToolArgs

    async def execute(self, args: ReadDataWarehouseSchemaMCPToolArgs) -> str:
        return await self._build_tables_list()

    @database_sync_to_async(thread_sensitive=False)
    def _build_tables_list(self) -> str:
        database = self._get_database()
        hogql_context = self._get_default_hogql_context(database)

        core_tables = {"events", "groups", "persons", "sessions"}
        serialized = database.serialize(hogql_context, include_only=core_tables)

        lines: list[str] = ["# Core PostHog tables", ""]

        for table_name, table in serialized.items():
            lines.append(f"## Table `{table_name}`")
            for field in table.fields.values():
                lines.append(f"- {field.name} ({field.type})")
            lines.append("")

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
