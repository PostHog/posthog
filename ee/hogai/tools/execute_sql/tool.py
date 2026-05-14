from typing import Self
from uuid import uuid4

import structlog
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from posthog.schema import (
    ArtifactContentType,
    ArtifactSource,
    AssistantDataVisualizationChartSettings,
    AssistantDataVisualizationDisplayType,
    AssistantToolCallMessage,
    ChartDisplayType,
    ChartSettings,
    DataVisualizationNode,
    HogQLFilters,
    HogQLQuery,
    VisualizationArtifactContent,
)

from posthog.hogql.feature_extractor import HogQLFeatureExtractor
from posthog.hogql.parser import parse_select

from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from products.catalog.backend.facade.api import CatalogAPI
from products.catalog.backend.facade.contracts import CatalogNodeContextDTO

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.chat_agent.sql.mixins import HogQLGeneratorMixin
from ee.hogai.chat_agent.sql.prompts import (
    SQL_EXPRESSIONS_DOCS,
    SQL_SUPPORTED_AGGREGATIONS_DOCS,
    SQL_SUPPORTED_FUNCTIONS_DOCS,
)
from ee.hogai.context import AssistantContextManager
from ee.hogai.context.insight.context import InsightContext
from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath

from .prompts import (
    EXECUTE_SQL_CONTEXT_PROMPT,
    EXECUTE_SQL_RECOVERABLE_ERROR_PROMPT,
    EXECUTE_SQL_SYSTEM_PROMPT,
    EXECUTE_SQL_UNRECOVERABLE_ERROR_PROMPT,
)

logger = structlog.get_logger(__name__)


class ExecuteSQLToolArgs(BaseModel):
    query: str = Field(description="The final SQL query to be executed.")
    filters: HogQLFilters | None = Field(
        default=None,
        description=(
            "Optional filters applied through `{filters}` placeholders in the query. "
            "Use this when editing a SQL editor query that already uses `{filters}` and the user asks to change "
            "dateRange, property filters, or test-account filtering. Set this to an empty object to clear existing "
            "SQL editor filters while preserving the `{filters}` placeholder."
        ),
    )
    viz_title: str = Field(
        description="Short, concise name of the SQL query (2-5 words) that will be displayed as a header in the visualization."
    )
    viz_description: str = Field(
        description="Short, concise summary of the SQL query (1 sentence) that will be displayed as a description in the visualization."
    )
    display: AssistantDataVisualizationDisplayType | None = Field(
        default=None,
        description="Optional visualization type for the SQL result, such as ActionsBar or ActionsLineGraph. Use this when the user asks for a chart.",
    )
    chart_settings: AssistantDataVisualizationChartSettings | None = Field(
        default=None,
        description="Optional chart settings for the SQL result, including X-axis label, left Y-axis label, right Y-axis label, and which Y series uses the right axis.",
    )


class ExecuteSQLTool(HogQLGeneratorMixin, MaxTool):
    name: str = "execute_sql"
    args_schema: type[BaseModel] = ExecuteSQLToolArgs
    context_prompt_template: str = EXECUTE_SQL_CONTEXT_PROMPT

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
    ) -> Self:
        prompt = format_prompt_string(
            EXECUTE_SQL_SYSTEM_PROMPT,
            sql_expressions_docs=SQL_EXPRESSIONS_DOCS,
            sql_supported_functions_docs=SQL_SUPPORTED_FUNCTIONS_DOCS,
            sql_supported_aggregations_docs=SQL_SUPPORTED_AGGREGATIONS_DOCS,
        )
        return cls(team=team, user=user, state=state, node_path=node_path, config=config, description=prompt)

    async def _arun_impl(
        self,
        query: str,
        viz_title: str,
        viz_description: str,
        filters: HogQLFilters | None = None,
        display: AssistantDataVisualizationDisplayType | None = None,
        chart_settings: AssistantDataVisualizationChartSettings | dict[str, object] | None = None,
    ) -> tuple[str, ToolMessagesArtifact | None]:
        parsed_query = self._parse_output({"query": query})
        try:
            await self._quality_check_output(
                output=parsed_query,
            )
        except PydanticOutputParserException as e:
            return format_prompt_string(EXECUTE_SQL_RECOVERABLE_ERROR_PROMPT, error=str(e)), None

        source_query = (
            parsed_query.query.source.model_copy(update={"filters": filters})
            if filters is not None
            else parsed_query.query.source
        )
        artifact_query = parsed_query.query.model_copy(update={"source": source_query})
        if display or chart_settings:
            if isinstance(chart_settings, AssistantDataVisualizationChartSettings):
                chart_settings_data = chart_settings.model_dump(mode="json", exclude_none=True)
            elif chart_settings:
                chart_settings_data = AssistantDataVisualizationChartSettings.model_validate(chart_settings).model_dump(
                    mode="json", exclude_none=True
                )
            else:
                chart_settings_data = None

            artifact_query = DataVisualizationNode(
                source=source_query,
                display=ChartDisplayType(display) if display else None,
                chartSettings=ChartSettings.model_validate(chart_settings_data) if chart_settings_data else None,
            )

        # Display an ephemeral visualization message to the user.
        artifact = await self._context_manager.artifacts.acreate(
            VisualizationArtifactContent(query=artifact_query, name=viz_title, description=viz_description),
            "SQL Query",
        )
        artifact_message = self._context_manager.artifacts.create_message(
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
            content_type=ArtifactContentType.VISUALIZATION,
        )

        insight_context = InsightContext(
            team=self._team,
            query=artifact_query,
            name=viz_title,
            description=viz_description,
            insight_id=artifact_message.artifact_id,
            user=self._user,
        )

        try:
            result = await insight_context.execute_and_format()
        except MaxToolRetryableError as e:
            return format_prompt_string(EXECUTE_SQL_RECOVERABLE_ERROR_PROMPT, error=str(e)), None
        except Exception:
            return EXECUTE_SQL_UNRECOVERABLE_ERROR_PROMPT, None

        catalog_block = await self._build_catalog_context_block(source_query)
        if catalog_block:
            result = f"{catalog_block}\n\n{result}"

        tool_payload: str | dict[str, object]
        if filters is not None:
            tool_payload = source_query.model_dump(mode="json", exclude_none=True)
        else:
            tool_payload = artifact_query.source.query

        return "", ToolMessagesArtifact(
            messages=[
                artifact_message,
                AssistantToolCallMessage(
                    content=result,
                    id=str(uuid4()),
                    tool_call_id=self.tool_call_id,
                    ui_payload={self.get_name(): tool_payload},
                ),
            ]
        )

    async def _build_catalog_context_block(self, source_query: HogQLQuery) -> str:
        """Extract FROM/JOIN tables from the agent's HogQL query and return a `# Catalog context`
        block to prepend to the SQL result.

        The agent often hits `execute_sql` without a prior `read_data`, so we surface the
        catalog's notes (descriptions, declared joins, user annotations) here too. Failures
        in parsing / lookup never block the SQL result — we just return an empty block.
        """
        if not source_query.query:
            return ""
        try:
            ast = parse_select(source_query.query)
        except Exception as e:
            logger.debug("execute_sql.catalog_context_parse_failed", error=str(e))
            return ""
        extractor = HogQLFeatureExtractor()
        extractor.visit(ast)
        if not extractor.tables:
            return ""

        contexts: list[CatalogNodeContextDTO] = []
        for table_name in sorted(extractor.tables):
            ctx = await database_sync_to_async(CatalogAPI.get_node_context)(self._team, table_name)
            if ctx is not None:
                contexts.append(ctx)
        if not contexts:
            return ""

        lines = ["# Catalog context"]
        for ctx in contexts:
            lines.append("")
            lines.append(f"## `{ctx.name}` ({ctx.kind})")
            if ctx.description:
                lines.append(ctx.description)
            described_columns = [c for c in ctx.columns if c.description]
            if described_columns:
                lines.append("Columns:")
                for col in described_columns:
                    lines.append(f"- {col.name} — {col.description}")
            joins = list(ctx.outgoing_joins) + list(ctx.incoming_joins)
            if joins:
                lines.append("Known joins:")
                for join in joins:
                    self_side = f"{ctx.name}.{join.self_column}" if join.self_column else ctx.name
                    other_side = f"{join.other_table}.{join.other_column}" if join.other_column else join.other_table
                    reasoning = f" — {join.reasoning}" if join.reasoning else ""
                    lines.append(f"- {self_side} ↔ {other_side} ({join.kind}){reasoning}")
        return "\n".join(lines)
