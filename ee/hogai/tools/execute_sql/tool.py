from typing import Self
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from posthog.schema import ArtifactContentType, ArtifactSource, AssistantToolCallMessage, VisualizationArtifactContent

from posthog.models import Team, User

from ee.hogai.chat_agent.sql.prompts import (
    SQL_EXPRESSIONS_DOCS,
    SQL_SUPPORTED_AGGREGATIONS_DOCS,
    SQL_SUPPORTED_FUNCTIONS_DOCS,
)
from ee.hogai.context import AssistantContextManager
from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath

from .core import HogQLValidationError, execute_hogql_query, validate_hogql
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


class ExecuteSQLTool(MaxTool):
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
        self, query: str, viz_title: str, viz_description: str
    ) -> tuple[str, ToolMessagesArtifact | None]:
        # Validate the HogQL query using shared core logic
        try:
            validated_query = await validate_hogql(query, self._team)
        except HogQLValidationError as e:
            return format_prompt_string(EXECUTE_SQL_RECOVERABLE_ERROR_PROMPT, error=str(e)), None

        # Display an ephemeral visualization message to the user.
        artifact = await self._context_manager.artifacts.acreate(
            VisualizationArtifactContent(query=validated_query, name=viz_title, description=viz_description),
            "SQL Query",
        )
        artifact_message = self._context_manager.artifacts.create_message(
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
            content_type=ArtifactContentType.VISUALIZATION,
        )

        # Execute the query using shared core logic
        try:
            result = await execute_hogql_query(
                team=self._team,
                query=validated_query,
                name=viz_title,
                description=viz_description,
                insight_id=artifact_message.artifact_id,
            )
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
                    ui_payload={self.get_name(): validated_query.query},
                ),
            ]
        )
