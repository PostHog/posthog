from typing import Literal, Self, Union
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from posthoganalytics import capture_exception
from pydantic import BaseModel, Field, create_model

from posthog.schema import (
    ArtifactContentType,
    AssistantToolCallMessage,
    NotebookArtifactContent,
    VisualizationArtifactContent,
)

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database

from posthog.models import Dashboard, Team, User
from posthog.sync import database_sync_to_async

from ee.hogai.artifacts.types import ModelArtifactResult
from ee.hogai.chat_agent.sql.mixins import HogQLDatabaseMixin
from ee.hogai.context.context import AssistantContextManager
from ee.hogai.context.dashboard.context import DashboardContext, DashboardInsightContext
from ee.hogai.context.insight.context import InsightContext
from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.tool_errors import MaxToolFatalError, MaxToolRetryableError
from ee.hogai.tools.read_billing_tool.tool import ReadBillingTool
from ee.hogai.tools.read_data.prompts import (
    BILLING_INSUFFICIENT_ACCESS_PROMPT,
    DASHBOARD_NOT_FOUND_PROMPT,
    INSIGHT_NOT_FOUND_PROMPT,
    READ_DATA_BILLING_PROMPT,
    READ_DATA_PROMPT,
    READ_DATA_WAREHOUSE_SCHEMA_PROMPT,
)
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.query import validate_assistant_query
from ee.hogai.utils.types.base import ArtifactRefMessage, AssistantState, NodePath
from ee.models.assistant import AgentArtifact


class ReadDataWarehouseSchema(BaseModel):
    """Returns core PostHog tables (events, groups, persons, sessions) with their full schemas, plus a list of available data warehouse tables and views (names only)."""

    kind: Literal["data_warehouse_schema"] = "data_warehouse_schema"


class ReadDataWarehouseTableSchema(BaseModel):
    """Returns the full schema with columns for a specific data warehouse table or view."""

    kind: Literal["data_warehouse_table"] = "data_warehouse_table"
    table_name: str = Field(description="The name of the table to read the schema for.")


class ReadInsight(BaseModel):
    """Retrieves an existing saved insight by its short ID."""

    kind: Literal["insight"] = "insight"
    insight_id: str = Field(description="The string ID of the insight.")
    execute: bool = Field(
        default=False,
        description="If true, executes the insight query and returns results. If false, returns only the insight definition.",
    )


class ReadDashboard(BaseModel):
    """Retrieves an existing dashboard by its ID."""

    kind: Literal["dashboard"] = "dashboard"
    dashboard_id: str = Field(description="The numeric ID of the dashboard.")
    execute: bool = Field(
        default=False,
        description="If true, executes all insight queries in the dashboard and returns results. If false, returns only the dashboard and insight definitions.",
    )


class ReadBillingInfo(BaseModel):
    """Retrieves billing information for the organization."""

    kind: Literal["billing_info"] = "billing_info"


class ReadArtifact(BaseModel):
    """Reads a specific artifact by ID."""

    kind: Literal["artifact"] = "artifact"
    artifact_id: str = Field(description="The ID of the artifact to read.")


class ReadErrorTrackingIssue(BaseModel):
    """Retrieves error tracking issue details including stack trace for analysis."""

    kind: Literal["error_tracking_issue"] = "error_tracking_issue"
    issue_id: str = Field(description="The UUID of the error tracking issue.")


ReadDataQuery = (
    ReadDataWarehouseSchema
    | ReadDataWarehouseTableSchema
    | ReadInsight
    | ReadDashboard
    | ReadBillingInfo
    | ReadErrorTrackingIssue
    | ReadArtifact
)


class _InternalReadDataToolArgs(BaseModel):
    query: ReadDataQuery = Field(..., discriminator="kind")


class ReadDataTool(HogQLDatabaseMixin, MaxTool):
    name: Literal["read_data"] = "read_data"
    description: str = READ_DATA_PROMPT
    context_prompt_template: str = (
        "Reads user data created in PostHog (data warehouse schema, saved insights, dashboards, billing information)"
    )

    @classmethod
    async def create_tool_class(
        cls,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...] | None = None,
        state: AssistantState | None = None,
        config: RunnableConfig | None = None,
        context_manager: AssistantContextManager | None = None,
        can_read_artifacts: bool = False,
    ) -> Self:
        """
        Factory that creates a ReadDataTool with a dynamic args schema.

        Override this factory to add additional args schemas or descriptions.
        """
        kinds: list[type[BaseModel]] = []
        prompt_vars: dict[str, str] = {}

        if not context_manager:
            context_manager = AssistantContextManager(team, user, config)

        has_billing_access = await context_manager.check_user_has_billing_access()

        if has_billing_access:
            prompt_vars["billing_prompt"] = READ_DATA_BILLING_PROMPT
            kinds.append(ReadBillingInfo)

        base_kinds: tuple[type[BaseModel], ...] = (
            ReadDataWarehouseSchema,
            ReadDataWarehouseTableSchema,
            ReadInsight,
            ReadDashboard,
            ReadErrorTrackingIssue,
            ReadArtifact,
        )
        ReadDataKind = Union[tuple(base_kinds + tuple(kinds))]  # type: ignore[valid-type]

        ReadDataToolArgs = create_model(
            "ReadDataToolArgs",
            __base__=BaseModel,
            query=(
                ReadDataKind,
                Field(discriminator="kind"),
            ),
        )

        description = format_prompt_string(READ_DATA_PROMPT, template_format="mustache", **prompt_vars).strip()

        return cls(
            team=team,
            user=user,
            state=state,
            node_path=node_path,
            config=config,
            args_schema=ReadDataToolArgs,
            description=description,
            context_manager=context_manager,
        )

    async def _arun_impl(self, query: dict) -> tuple[str, ToolMessagesArtifact | None]:
        validated_query = _InternalReadDataToolArgs(query=query).query
        match validated_query:
            case ReadBillingInfo():
                has_access = await self._context_manager.check_user_has_billing_access()
                if not has_access:
                    raise MaxToolFatalError(BILLING_INSUFFICIENT_ACCESS_PROMPT)
                billing_tool = ReadBillingTool(
                    team=self._team,
                    user=self._user,
                    state=self._state,
                    config=self._config,
                    context_manager=self._context_manager,
                )
                result = await billing_tool.execute()
                return result, None
            case ReadDataWarehouseSchema():
                return await self._read_data_warehouse_schema(), None
            case ReadDataWarehouseTableSchema() as data_warehouse_table:
                return await self._read_data_warehouse_table_schema(data_warehouse_table.table_name), None
            case ReadArtifact() as schema:
                return await self._read_artifact(schema.artifact_id), None
            case ReadInsight() as schema:
                return await self._read_insight(schema.insight_id, schema.execute)
            case ReadDashboard() as schema:
                return await self._read_dashboard(schema.dashboard_id, schema.execute)
            case ReadErrorTrackingIssue() as schema:
                return await self._read_error_tracking_issue(schema.issue_id), None

    async def _read_insight(
        self, artifact_or_insight_id: str, execute: bool
    ) -> tuple[str, ToolMessagesArtifact | None]:
        # Fetch the artifact content along with its source
        result = await self._context_manager.artifacts.aget_visualization(self._state.messages, artifact_or_insight_id)

        if result is None:
            raise MaxToolRetryableError(INSIGHT_NOT_FOUND_PROMPT.format(short_id=artifact_or_insight_id))

        insight_name = result.content.name or f"Insight {artifact_or_insight_id}"

        # Create insight context
        context = InsightContext(
            team=self._team,
            query=result.content.query,
            name=insight_name,
            description=result.content.description,
            insight_id=artifact_or_insight_id,
            insight_model_id=result.model.id if isinstance(result, ModelArtifactResult) else None,
            insight_short_id=result.model.short_id if isinstance(result, ModelArtifactResult) else None,
        )

        # The agent wants to read the schema, just return it
        if not execute:
            text_result = await context.format_schema()
            return text_result, None

        # Create a new artifact message, so the user can see the results in the UI
        artifact_message = ArtifactRefMessage(
            content_type=ArtifactContentType.VISUALIZATION,
            artifact_id=artifact_or_insight_id,
            source=result.source,
            id=str(uuid4()),
        )

        # Execute the query and return the results
        text_result = await context.execute_and_format()
        tool_call_message = AssistantToolCallMessage(
            content=text_result,
            id=str(uuid4()),
            tool_call_id=self.tool_call_id,
        )

        return "", ToolMessagesArtifact(messages=[artifact_message, tool_call_message])

    async def _read_data_warehouse_schema(self) -> str:
        database = await self._aget_database()
        hogql_context = self._get_default_hogql_context(database)
        return await self._build_tables_list(database, hogql_context)

    async def _read_data_warehouse_table_schema(self, table_name: str) -> str:
        database = await self._aget_database()
        hogql_context = self._get_default_hogql_context(database)
        return await self._build_table_schema(database, hogql_context, table_name)

    @database_sync_to_async
    def _build_tables_list(self, database: Database, hogql_context: HogQLContext) -> str:
        core_tables = {"events", "groups", "persons", "sessions"}
        serialized = database.serialize(hogql_context, include_only=core_tables)

        system_table_lines: list[str] = []
        for table_name, table in serialized.items():
            system_table_lines.append(f"## Table `{table_name}`")
            for field in table.fields.values():
                system_table_lines.append(f"- {field.name} ({field.type})")
            system_table_lines.append("")

        warehouse_tables = database.get_warehouse_table_names()
        views = database.get_view_names()

        listify = lambda items: "\n".join(f"- {item}" for item in sorted(items))

        return format_prompt_string(
            READ_DATA_WAREHOUSE_SCHEMA_PROMPT,
            template_format="mustache",
            posthog_tables="\n".join(system_table_lines),
            data_warehouse_tables=listify(warehouse_tables),
            data_warehouse_views=listify(views),
        )

    @database_sync_to_async
    def _build_table_schema(self, database: Database, hogql_context: HogQLContext, table_name: str) -> str:
        # Load tables on demand: warehouse first, then views, then posthog tables
        table_sources = [
            database.get_warehouse_table_names,
            database.get_view_names,
            database.get_posthog_table_names,
        ]

        table_found = False
        all_tables: list[str] = []
        for get_tables in table_sources:
            tables = get_tables()
            if table_name in tables:
                table_found = True
                break
            all_tables.extend(tables)

        if not table_found:
            available = ", ".join(sorted(all_tables)[:20])
            return f"Table `{table_name}` not found. Available tables include: {available}..."

        serialized = database.serialize(hogql_context, include_only={table_name})

        if table_name not in serialized:
            return f"Could not serialize schema for table `{table_name}`."

        table = serialized[table_name]
        lines = [f"Table `{table_name}` with fields:"]
        for field in table.fields.values():
            lines.append(f"- {field.name} ({field.type})")

        return "\n".join(lines)

    async def _read_dashboard(self, dashboard_id: str, execute: bool) -> tuple[str, ToolMessagesArtifact | None]:
        try:
            dashboard = (
                await Dashboard.objects.select_related("team")
                .prefetch_related("tiles__insight")
                .aget(id=int(dashboard_id), team=self._team, deleted=False)
            )
        except (Dashboard.DoesNotExist, ValueError):
            raise MaxToolFatalError(DASHBOARD_NOT_FOUND_PROMPT.format(dashboard_id=dashboard_id))

        dashboard_name = dashboard.name or f"Dashboard {dashboard_id}"
        tiles = [
            tile
            async for tile in dashboard.tiles.exclude(insight__deleted=True, deleted=True).select_related("insight")
        ]

        # Build DashboardInsightContext models for all tiles
        insights_data: list[DashboardInsightContext] = []
        for tile in tiles:
            insight = tile.insight
            if not insight or not insight.query:
                continue

            # Parse and validate the query
            query = insight.query
            if isinstance(query, dict):
                # Handle wrapped queries
                if query.get("source"):
                    query = query.get("source")
                if not query:
                    continue
                # Convert dict to proper query model

                try:
                    query = validate_assistant_query(query)
                except Exception as e:
                    capture_exception(
                        e,
                        distinct_id=self._user.distinct_id,
                        properties=self._get_debug_props(self._config),
                    )
                    continue

            insight_name = insight.name or insight.derived_name or f"Insight {insight.short_id}"
            insights_data.append(
                DashboardInsightContext(
                    query=query,
                    name=insight_name,
                    description=insight.description,
                    short_id=insight.short_id,
                    db_id=insight.id,
                    layout=tile.layouts,
                )
            )

        # Create DashboardContext and execute or format schema
        dashboard_ctx = DashboardContext(
            team=self._team,
            insights_data=insights_data,
            name=dashboard_name,
            description=dashboard.description,
            dashboard_id=dashboard_id,
        )

        if execute:
            text_result = await dashboard_ctx.execute_and_format()
        else:
            text_result = await dashboard_ctx.format_schema()

        return text_result, None

    async def _read_error_tracking_issue(self, issue_id: str) -> str:
        from ee.hogai.context.error_tracking import ErrorTrackingIssueContext

        context = ErrorTrackingIssueContext(
            team=self._team,
            issue_id=issue_id,
        )
        return await context.execute_and_format()

    async def _read_artifact(self, artifact_id: str) -> str:
        try:
            content = await self._context_manager.artifacts.aget(artifact_id)
        except AgentArtifact.DoesNotExist:
            raise MaxToolRetryableError(f"Artifact with id={artifact_id} not found.")

        match content:
            case VisualizationArtifactContent():
                context = InsightContext(
                    team=self._team,
                    query=content.query,
                    name=content.name,
                    description=content.description,
                    insight_id=artifact_id,
                )
                return await context.format_schema()

            case NotebookArtifactContent():
                lines = [f"# Notebook: {content.title or 'Untitled'}"]
                for block in content.blocks:
                    if hasattr(block, "content"):
                        lines.append(block.content)
                    elif hasattr(block, "query"):
                        lines.append(f"[Visualization: {block.query.model_dump_json(exclude_none=True)}]")
                return "\n\n".join(lines)

        raise MaxToolFatalError(f"Unknown artifact type: {type(content).__name__}")
