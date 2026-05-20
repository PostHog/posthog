from typing import Literal, Union

from pydantic import BaseModel, Field

from posthog.sync import database_sync_to_async

from ee.hogai.chat_agent.sql.mixins import HogQLDatabaseMixin
from ee.hogai.mcp_tool import MCPTool, mcp_tool_registry

_PERSONS_DB_TABLES = {"group_type_mappings", "groups"}
_CORE_TABLE_NAMES = ["events", "groups", "persons", "sessions"]


class ListDataWarehouseCatalog(BaseModel):
    """Returns core PostHog table schemas (events, groups, persons, sessions) plus a catalog listing of every available warehouse table, system table, and view by name. Call this first if you don't yet know which tables exist."""

    kind: Literal["data_warehouse_catalog"] = "data_warehouse_catalog"


class GetDataWarehouseTables(BaseModel):
    """Returns full column schemas for the named warehouse, system, view, or core tables. Use this after `data_warehouse_catalog` once you know which tables you need."""

    kind: Literal["data_warehouse_tables"] = "data_warehouse_tables"
    table_names: list[str] = Field(
        min_length=1,
        description="Specific warehouse, system, view, or core table names to fetch schemas for.",
    )


DataWarehouseSchemaQuery = Union[ListDataWarehouseCatalog, GetDataWarehouseTables]


class ReadDataWarehouseSchemaMCPToolArgs(BaseModel):
    query: DataWarehouseSchemaQuery = Field(..., discriminator="kind")


@mcp_tool_registry.register(scopes=["warehouse_table:read", "warehouse_view:read"])
class ReadDataWarehouseSchemaMCPTool(HogQLDatabaseMixin, MCPTool[ReadDataWarehouseSchemaMCPToolArgs]):
    """
    MCP tool that returns core PostHog table schemas (events, groups, persons, sessions).

    This provides the data model information needed for writing HogQL queries.
    """

    name = "read_data_warehouse_schema"
    args_schema = ReadDataWarehouseSchemaMCPToolArgs

    async def execute(self, args: ReadDataWarehouseSchemaMCPToolArgs) -> str:
        match args.query:
            case GetDataWarehouseTables():
                return await self._build_specific_tables(args.query.table_names)
            case ListDataWarehouseCatalog():
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

    @staticmethod
    def _resolve_warehouse_canonical(name: str, warehouse_names: set[str]) -> str | None:
        # get_warehouse_table_names() returns both the canonical dotted form (e.g.
        # "hubspot.companies") and an underscored alias ("hubspot_companies").
        # database.serialize() only honors the dotted form, so if the agent asks
        # for the alias we map it back before calling serialize.
        if "." in name:
            return None
        parts = name.split("_")
        for i in range(1, len(parts)):
            candidate = ".".join(["_".join(parts[:i]), "_".join(parts[i:])])
            if candidate in warehouse_names:
                return candidate
        return None

    @database_sync_to_async(thread_sensitive=False)
    def _build_specific_tables(self, table_names: list[str]) -> str:
        database = self._get_database()
        hogql_context = self._get_default_hogql_context(database)

        warehouse_names = database.get_warehouse_table_names()

        # Order matters: the first source to claim a name wins the label.
        sources: list[tuple[str, list[str]]] = [
            ("data warehouse", warehouse_names),
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

        warehouse_set = set(warehouse_names)
        canonical_for: dict[str, str] = {}
        for n in ordered_requested:
            if n not in location_by_name:
                continue
            if location_by_name[n] == "data warehouse":
                canonical_for[n] = self._resolve_warehouse_canonical(n, warehouse_set) or n
            else:
                canonical_for[n] = n

        found = [n for n in ordered_requested if n in location_by_name]
        unrecognized = [n for n in ordered_requested if n not in location_by_name]

        serialized: dict[str, object] = {}
        if found:
            serialize_keys = {canonical_for[n] for n in found}
            serialized = database.serialize(hogql_context, include_only=serialize_keys)

        # Anything we marked found but serialize couldn't render falls back to
        # missing — otherwise the response silently drops it with no signal.
        unserialized = {n for n in found if canonical_for[n] not in serialized}
        missing_set = set(unrecognized) | unserialized
        missing = [n for n in ordered_requested if n in missing_set]

        lines: list[str] = ["# Requested tables", ""]
        for name in ordered_requested:
            if name not in location_by_name:
                continue
            canonical = canonical_for[name]
            if canonical not in serialized:
                continue
            table = serialized[canonical]
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
