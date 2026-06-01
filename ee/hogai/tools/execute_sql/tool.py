from typing import Self
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from posthog.schema import (
    ArtifactContentType,
    ArtifactSource,
    AssistantDataVisualizationChartSettings,
    AssistantDataVisualizationDisplayType,
    AssistantHogQLQuery,
    AssistantToolCallMessage,
    ChartDisplayType,
    ChartSettings,
    DataVisualizationNode,
    HogQLQuery,
    VisualizationArtifactContent,
)

from posthog.models import Team, User

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


class ExecuteSQLToolArgs(BaseModel):
    query: str = Field(description="The final SQL query to be executed.")
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

        artifact_query: AssistantHogQLQuery | DataVisualizationNode = parsed_query.query
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
                source=HogQLQuery(**parsed_query.query.model_dump(mode="json", exclude_none=True)),
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
            query=parsed_query.query,
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

        return "", ToolMessagesArtifact(
            messages=[
                artifact_message,
                AssistantToolCallMessage(
                    content=result,
                    id=str(uuid4()),
                    tool_call_id=self.tool_call_id,
                    ui_payload={self.get_name(): parsed_query.query.query},
                ),
            ]
        )
