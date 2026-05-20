from typing import Literal

from pydantic import BaseModel, Field

from posthog.sync import database_sync_to_async

from ee.hogai.chat_agent.sql.mixins import HogQLDatabaseMixin
from ee.hogai.mcp_tool import MCPTool, mcp_tool_registry

_PERSONS_DB_TABLES = {"group_type_mappings", "groups"}
_CORE_TABLE_NAMES = ["events", "groups", "persons", "sessions"]


class ReadDataWarehouseSchemaQuery(BaseModel):
    kind: Literal["data_warehouse_schema"] = "data_warehouse_schema"
    table_names: list[str] | None = Field(
        default=None,
        description=(
            "Optional list of specific warehouse, system, view, or core table names. "
            "If provided, returns schemas only for those tables (catalog sections are omitted). "
            "If omitted, returns core tables plus the full catalog."
        ),
    )


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
        if args.query.table_names:
            return await self._build_specific_tables(args.query.table_names)
        return await self._build_tables_list()

    @database_sync_to_async(thread_sensitive=False)
    def _build_tables_list(self) -> str:
        database = self._get_database()
        hogql_context = self._get_default_hogql_context(database)

        serialized = database.serialize(hogql_context, include_only=set(_CORE_TABLE_NAMES))

        lines: list[str] = ["# Core PostHog tables", ""]

        for table_name, table in serialized.items():
            lines.append(f"## Table `{table_name}`")
            for field in table.fields.values():
                lines.append(f"- {field.name} ({field.type})")
            lines.append("")

        warehouse_tables = database.get_warehouse_table_names()
        # Filter out tables that live in the persons database and can't be queried via ClickHouse
        system_tables = [t for t in database.get_system_table_names() if t not in _PERSONS_DB_TABLES]
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

    @database_sync_to_async(thread_sensitive=False)
    def _build_specific_tables(self, table_names: list[str]) -> str:
        database = self._get_database()
        hogql_context = self._get_default_hogql_context(database)

        # Order matters: the first source to claim a name wins the label.
        sources: list[tuple[str, list[str]]] = [
            ("data warehouse", database.get_warehouse_table_names()),
            ("system", [t for t in database.get_system_table_names() if t not in _PERSONS_DB_TABLES]),
            ("view", database.get_view_names()),
            ("core", list(_CORE_TABLE_NAMES)),
        ]
        location_by_name: dict[str, str] = {}
        all_names: set[str] = set()
        for label, names in sources:
            for n in names:
                location_by_name.setdefault(n, label)
                all_names.add(n)

        seen: set[str] = set()
        ordered_requested: list[str] = []
        for n in table_names:
            if n not in seen:
                seen.add(n)
                ordered_requested.append(n)

        found = [n for n in ordered_requested if n in location_by_name]
        missing = [n for n in ordered_requested if n not in location_by_name]

        lines: list[str] = ["# Requested tables", ""]
        if found:
            serialized = database.serialize(hogql_context, include_only=set(found))
            for name in ordered_requested:
                if name not in serialized:
                    continue
                table = serialized[name]
                lines.append(f"## Table `{name}` ({location_by_name[name]})")
                for field in table.fields.values():
                    lines.append(f"- {field.name} ({field.type})")
                lines.append("")

        if missing:
            suggestions = ", ".join(sorted(all_names)[:10])
            lines.append("## Not found")
            for name in missing:
                lines.append(f"- `{name}` — available tables include: {suggestions}")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"
