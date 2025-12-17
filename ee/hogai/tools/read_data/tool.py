import json
from typing import Any, Literal, Self, Union
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from posthoganalytics import capture_exception
from pydantic import BaseModel, Field, create_model

from posthog.schema import (
    ArtifactContentType,
    ArtifactMessage,
    ArtifactSource,
    AssistantToolCallMessage,
    ErrorTrackingFiltersArtifactContent,
    ErrorTrackingImpactArtifactContent,
    VisualizationArtifactContent,
)

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database

from posthog.models import Dashboard, Team, User
from posthog.sync import database_sync_to_async

from products.error_tracking.backend.api.issues import ErrorTrackingIssueFullSerializer
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueFingerprintV2

from ee.hogai.artifacts.manager import ModelArtifactResult
from ee.hogai.chat_agent.sql.mixins import HogQLDatabaseMixin
from ee.hogai.context.context import AssistantContextManager
from ee.hogai.context.dashboard.context import DashboardContext, DashboardInsightContext
from ee.hogai.context.error_tracking import ErrorTrackingFiltersContext
from ee.hogai.context.insight.context import InsightContext
from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.tool_errors import MaxToolFatalError, MaxToolRetryableError
from ee.hogai.tools.read_billing_tool.tool import ReadBillingTool
from ee.hogai.tools.read_data.prompts import (
    BILLING_INSUFFICIENT_ACCESS_PROMPT,
    DASHBOARD_NOT_FOUND_PROMPT,
    INSIGHT_NOT_FOUND_PROMPT,
    READ_DATA_ARTIFACTS_PROMPT,
    READ_DATA_BILLING_PROMPT,
    READ_DATA_ERROR_TRACKING_PROMPT,
    READ_DATA_PROMPT,
    READ_DATA_WAREHOUSE_SCHEMA_PROMPT,
)
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.query import validate_assistant_query
from ee.hogai.utils.types.base import ArtifactRefMessage, AssistantState, NodePath

ErrorTrackingStatus = Literal["active", "resolved", "suppressed"]


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


class ReadArtifacts(BaseModel):
    """Reads conversation artifacts created by the agent."""

    kind: Literal["artifacts"] = "artifacts"


class ReadErrorTrackingIssue(BaseModel):
    """Retrieves an error tracking issue by its ID."""

    kind: Literal["error_tracking_issue"] = "error_tracking_issue"
    issue_id: str = Field(description="The issue ID from /error_tracking/<id>.")


class ReadErrorTrackingFilters(BaseModel):
    """Query error tracking issues with filters."""

    kind: Literal["error_tracking_filters"] = "error_tracking_filters"
    status: ErrorTrackingStatus | None = Field(
        default=None,
        description="Filter by status: 'active', 'resolved', or 'suppressed'.",
    )
    search_query: str | None = Field(
        default=None,
        description="Search issues by name (case-insensitive contains match).",
    )
    date_from: str | None = Field(
        default=None,
        description="Start date for filtering (e.g., '-7d', '-30d', '2024-01-01').",
    )
    date_to: str | None = Field(
        default=None,
        description="End date for filtering (e.g., '2024-12-31', or null for 'now').",
    )
    execute: bool = Field(
        default=False,
        description="If true, return matching issues. If false, just returns the filter artifact.",
    )
    limit: int = Field(
        default=5,
        description="Max issues to return when executing (1-25).",
    )


ReadDataQuery = (
    ReadDataWarehouseSchema
    | ReadDataWarehouseTableSchema
    | ReadInsight
    | ReadDashboard
    | ReadBillingInfo
    | ReadArtifacts
    | ReadErrorTrackingIssue
    | ReadErrorTrackingFilters
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
        kinds: list[type[BaseModel]] = [ReadErrorTrackingIssue, ReadErrorTrackingFilters]
        prompt_vars: dict[str, str] = {"error_tracking_prompt": READ_DATA_ERROR_TRACKING_PROMPT}

        if not context_manager:
            context_manager = AssistantContextManager(team, user, config)

        has_billing_access = await context_manager.check_user_has_billing_access()

        # Subagents don't have access to artifacts
        if can_read_artifacts:
            prompt_vars["artifacts_prompt"] = READ_DATA_ARTIFACTS_PROMPT
            kinds.append(ReadArtifacts)
        if has_billing_access:
            prompt_vars["billing_prompt"] = READ_DATA_BILLING_PROMPT
            kinds.append(ReadBillingInfo)

        ReadDataKind = Union[ReadDataWarehouseSchema, ReadDataWarehouseTableSchema, ReadInsight, ReadDashboard, *kinds]  # type: ignore

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
            case ReadArtifacts():
                return await self._read_artifacts()
            case ReadInsight() as schema:
                return await self._read_insight(schema.insight_id, schema.execute)
            case ReadDashboard() as schema:
                return await self._read_dashboard(schema.dashboard_id, schema.execute)
            case ReadErrorTrackingIssue() as schema:
                return await self._read_error_tracking_issue(issue_id=schema.issue_id)
            case ReadErrorTrackingFilters() as schema:
                return await self._read_error_tracking_filters(
                    status=schema.status,
                    search_query=schema.search_query,
                    date_from=schema.date_from,
                    date_to=schema.date_to,
                    execute=schema.execute,
                    limit=schema.limit,
                )

    async def _read_insight(
        self, artifact_or_insight_id: str, execute: bool
    ) -> tuple[str, ToolMessagesArtifact | None]:
        # Fetch the artifact content along with its source
        result = await self._context_manager.artifacts.aget_insight_with_source(
            self._state.messages, artifact_or_insight_id
        )

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

    async def _read_artifacts(self) -> tuple[str, None]:
        conversation_artifacts = await self._context_manager.artifacts.aget_conversation_artifact_messages()
        formatted_artifacts = []

        for message in conversation_artifacts:
            formatted = self._format_artifact_message(message)
            if formatted:
                formatted_artifacts.append(formatted)

        if len(formatted_artifacts) == 0:
            return "No artifacts available", None
        return "\n\n".join(formatted_artifacts), None

    def _format_artifact_message(self, message: ArtifactMessage) -> str | None:
        """Format an artifact message based on its content type."""
        content = message.content
        if isinstance(content, VisualizationArtifactContent):
            return f"- id: {message.artifact_id}\n- type: visualization\n- name: {content.name}\n- description: {content.description}\n- query: {content.query}"
        elif isinstance(content, ErrorTrackingFiltersArtifactContent):
            filters = content.filters
            date_range = filters.get("dateRange", {})
            return f"- id: {message.artifact_id}\n- type: error_tracking_filters\n- status: {filters.get('status')}\n- date_range: {date_range.get('date_from')} to {date_range.get('date_to')}"
        elif isinstance(content, ErrorTrackingImpactArtifactContent):
            return f"- id: {message.artifact_id}\n- type: error_tracking_impact\n- issue: {content.issue_name}\n- occurrences: {content.occurrences}\n- users: {content.users_affected}"
        return None

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
                        e, distinct_id=self._user.distinct_id, properties=self._get_debug_props(self._config)
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

    async def _read_error_tracking_issue(self, issue_id: str) -> tuple[str, None]:
        """
        Supports both:
        - numeric ID from `/error_tracking/<id>`
        - UUID issue id (ErrorTrackingIssue uses UUIDTModel)
        - fingerprint UUID passed as `issue_id` (resolve via ErrorTrackingIssueFingerprintV2)
        """
        issue_pk: str = issue_id.strip()

        # If `issue_id` is not an int, it may be a UUID (issue UUID) or a fingerprint.
        is_int = False
        try:
            _ = int(issue_pk)
            is_int = True
        except ValueError:
            is_int = False

        # Resolve fingerprint -> issue_id (UUID). Must be sync-to-async safe.
        if not is_int:
            record = await database_sync_to_async(
                lambda: ErrorTrackingIssueFingerprintV2.objects.select_related("issue")
                .filter(team_id=self._team.id, fingerprint=issue_pk)
                .first(),
                thread_sensitive=False,
            )()
            if record:
                issue_pk = str(record.issue_id)

        issue = await (
            ErrorTrackingIssue.objects.with_first_seen()
            .select_related("assignment")
            .prefetch_related("external_issues__integration")
            .prefetch_related("cohorts__cohort")
            .filter(team_id=self._team.id)
            .filter(id=issue_pk)
            .afirst()
        )
        if not issue:
            raise MaxToolRetryableError(f"The error tracking issue with id or fingerprint '{issue_id}' was not found.")

        # DRF serializer is sync code; wrap it to avoid async context issues.
        serialized = await database_sync_to_async(
            lambda: ErrorTrackingIssueFullSerializer(issue).data, thread_sensitive=False
        )()

        # Avoid relying on Django settings here (can be unavailable depending on runtime/import timing).
        # The frontend can build an absolute URL; we provide a stable relative path.
        url = f"/project/{self._team.id}/error_tracking/{serialized.get('id')}"

        text = json.dumps(
            {
                "error_tracking_issue_id": serialized.get("id"),
                "name": serialized.get("name"),
                "description": serialized.get("description"),
                "status": serialized.get("status"),
                "first_seen": serialized.get("first_seen"),
                "assignee": serialized.get("assignee"),
                "external_issues": serialized.get("external_issues"),
                "cohort": serialized.get("cohort"),
                "url": url,
                "input_id": issue_id,
                "resolved_id": serialized.get("id"),
            },
            indent=2,
            default=str,
        )
        return text, None

    async def _read_error_tracking_filters(
        self,
        status: ErrorTrackingStatus | None,
        search_query: str | None,
        date_from: str | None,
        date_to: str | None,
        execute: bool,
        limit: int,
    ) -> tuple[str, ToolMessagesArtifact | None]:
        limit = max(1, min(int(limit), 25))

        # Default date range if not provided
        effective_date_from = date_from if date_from is not None else "-7d"

        # Build filters dict for artifact/response
        filters_obj: dict[str, Any] = {"kind": "ErrorTrackingQuery"}
        if status:
            filters_obj["status"] = status
        if search_query:
            filters_obj["searchQuery"] = search_query
        filters_obj["dateRange"] = {"date_from": effective_date_from, "date_to": date_to}

        # Generate descriptive name based on filters
        name_parts: list[str] = []
        if status:
            name_parts.append(f"{status.capitalize()} issues")
        else:
            name_parts.append("Issues")
        if search_query:
            name_parts.append(f"matching '{search_query}'")
        artifact_name = " ".join(name_parts)

        # Create artifact
        content = ErrorTrackingFiltersArtifactContent(filters=filters_obj)
        artifact = await self._context_manager.artifacts.create_error_tracking_filters(
            content=content, name=artifact_name
        )

        artifact_ref_message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.ERROR_TRACKING_FILTERS,
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
        )

        if not execute:
            pretty = json.dumps(filters_obj, indent=2, default=str)
            text = f"Error tracking filters artifact created:\nArtifact ID: {artifact.short_id}\n\n{pretty}"
            tool_call_message = AssistantToolCallMessage(
                content=text,
                id=str(uuid4()),
                tool_call_id=self.tool_call_id,
            )
            return "", ToolMessagesArtifact(messages=[artifact_ref_message, tool_call_message])

        # Execute: use ErrorTrackingFiltersContext to query ClickHouse (same as UI)
        context = ErrorTrackingFiltersContext(
            team=self._team,
            status=status,
            search_query=search_query,
            date_from=effective_date_from,
            date_to=date_to,
            limit=limit,
        )
        issues = await context.execute()

        # Transform to output format with error_tracking_issue_id key and URL
        issues_out = []
        for issue in issues:
            data = issue.model_dump()
            data["error_tracking_issue_id"] = data.pop("id")
            data["url"] = f"/project/{self._team.id}/error_tracking/{issue.id}" if issue.id else None
            issues_out.append(data)

        text = json.dumps(
            {"filters_artifact_id": artifact.short_id, "limit": limit, "issues": issues_out},
            indent=2,
            default=str,
        )

        tool_call_message = AssistantToolCallMessage(
            content=text,
            id=str(uuid4()),
            tool_call_id=self.tool_call_id,
        )
        return "", ToolMessagesArtifact(messages=[artifact_ref_message, tool_call_message])
