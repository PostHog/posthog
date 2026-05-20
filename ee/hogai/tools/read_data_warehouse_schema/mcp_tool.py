from typing import Literal

from pydantic import BaseModel, Field

from posthog.sync import database_sync_to_async

from ee.hogai.chat_agent.sql.mixins import HogQLDatabaseMixin
from ee.hogai.mcp_tool import MCPTool, mcp_tool_registry

Section = Literal["core", "warehouse", "views", "system"]
ALL_SECTIONS: tuple[Section, ...] = ("core", "warehouse", "views", "system")

# Cap how much of a failed view's `latest_error` we surface — full ClickHouse errors
# can be many KB and would defeat the purpose of the filters.
_LATEST_ERROR_PREVIEW_CHARS = 200


class ReadDataWarehouseSchemaQuery(BaseModel):
    kind: Literal["data_warehouse_schema"] = "data_warehouse_schema"
    table_names: list[str] | None = Field(
        default=None,
        description=(
            "Optional list of exact table or view names to include in the output. "
            "Applied to all sections (core, warehouse, system, views). "
            "If omitted, every name in the included sections is listed."
        ),
    )
    include: list[Section] | None = Field(
        default=None,
        description=(
            "Optional list of sections to include in the output. Choose from: "
            "'core' (events/groups/persons/sessions with full column lists), "
            "'warehouse' (data warehouse tables), 'views' (saved query views), "
            "'system' (PostHog Postgres tables exposed as `system.*`). "
            "Defaults to all sections."
        ),
    )


class ReadDataWarehouseSchemaMCPToolArgs(BaseModel):
    query: ReadDataWarehouseSchemaQuery


@mcp_tool_registry.register(scopes=["warehouse_table:read", "warehouse_view:read"])
class ReadDataWarehouseSchemaMCPTool(HogQLDatabaseMixin, MCPTool[ReadDataWarehouseSchemaMCPToolArgs]):
    """
    MCP tool that returns core PostHog table schemas (events, groups, persons, sessions)
    plus the names of warehouse tables, system tables, and views available for HogQL queries.

    Pass `query.table_names` to scope the output to specific tables, and `query.include`
    to limit which sections (core/warehouse/views/system) appear. Views also surface
    their last-run `status` and any `latest_error` so callers can skip broken ones
    before issuing `execute-sql`.
    """

    name = "read_data_warehouse_schema"
    args_schema = ReadDataWarehouseSchemaMCPToolArgs

    async def execute(self, args: ReadDataWarehouseSchemaMCPToolArgs) -> str:
        sections = tuple(args.query.include) if args.query.include else ALL_SECTIONS
        return await self._build_tables_list(
            table_names=args.query.table_names,
            sections=sections,
        )

    @database_sync_to_async(thread_sensitive=False)
    def _build_tables_list(self, table_names: list[str] | None, sections: tuple[Section, ...]) -> str:
        from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

        database = self._get_database()
        hogql_context = self._get_default_hogql_context(database)

        wanted: set[str] | None = set(table_names) if table_names else None

        def in_filter(name: str) -> bool:
            return wanted is None or name in wanted

        def listify(items: list[str]) -> str:
            return "\n".join(f"- {item}" for item in sorted(items))

        out: list[str] = []

        if "core" in sections:
            core_tables = {"events", "groups", "persons", "sessions"}
            if wanted is not None:
                core_tables = core_tables & wanted
            if core_tables:
                serialized = database.serialize(hogql_context, include_only=core_tables)
                out.append("# Core PostHog tables")
                out.append("")
                for table_name, table in serialized.items():
                    out.append(f"## Table `{table_name}`")
                    for field in table.fields.values():
                        out.append(f"- {field.name} ({field.type})")
                    out.append("")

        if "warehouse" in sections:
            warehouse_tables = [t for t in database.get_warehouse_table_names() if in_filter(t)]
            if warehouse_tables:
                out.append("# Data warehouse tables")
                out.append(listify(warehouse_tables))
                out.append("")

        if "system" in sections:
            persons_db_tables = {"group_type_mappings", "groups"}
            system_tables = [
                t for t in database.get_system_table_names() if t not in persons_db_tables and in_filter(t)
            ]
            if system_tables:
                out.append("# PostHog Postgres tables")
                out.append(listify(system_tables))
                out.append("")

        if "views" in sections:
            view_names = [v for v in database.get_view_names() if in_filter(v)]
            if view_names:
                saved_queries = {
                    sq.name: sq
                    for sq in DataWarehouseSavedQuery.objects.filter(
                        team_id=self._team.pk, name__in=view_names, deleted=False
                    ).only("name", "status", "latest_error", "last_run_at")
                }
                out.append("# Data warehouse views")
                out.append(
                    "Listed with last-run status when known. Views with status=Failed or a `latest_error` "
                    "may fail when queried with `execute-sql` — verify before relying on them."
                )
                for view_name in sorted(view_names):
                    sq = saved_queries.get(view_name)
                    annotations: list[str] = []
                    if sq is not None:
                        if sq.status:
                            annotations.append(f"status={sq.status}")
                        if sq.latest_error:
                            err_preview = sq.latest_error[:_LATEST_ERROR_PREVIEW_CHARS].replace("\n", " ").strip()
                            if len(sq.latest_error) > _LATEST_ERROR_PREVIEW_CHARS:
                                err_preview += "…"
                            annotations.append(f"latest_error={err_preview!r}")
                    if annotations:
                        out.append(f"- {view_name} ({', '.join(annotations)})")
                    else:
                        out.append(f"- {view_name}")
                out.append("")

        return "\n".join(out).rstrip() + "\n"
