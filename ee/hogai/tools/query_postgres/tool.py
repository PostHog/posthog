"""
Max AI tool for querying PostgreSQL Django models via HogQL.

This tool allows the AI agent to query PostHog's configuration data
(dashboards, insights, feature flags, etc.) with automatic access control.
"""

from typing import Self
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from posthog.schema import AssistantToolCallMessage

from posthog.hogql.errors import QueryError
from posthog.hogql.postgres_executor import execute_postgres_query, format_postgres_result_for_llm

from posthog.models import Team, User

from ee.hogai.context import AssistantContextManager
from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath

from .prompts import (
    QUERY_POSTGRES_CONTEXT_PROMPT,
    QUERY_POSTGRES_RECOVERABLE_ERROR_PROMPT,
    QUERY_POSTGRES_UNRECOVERABLE_ERROR_PROMPT,
)


class QueryPostgresToolArgs(BaseModel):
    query: str = Field(description="The HogQL query to execute against PostgreSQL. Use SELECT statements only.")


class QueryPostgresTool(MaxTool):
    """
    Execute HogQL queries against PostgreSQL Django models.

    This tool allows querying PostHog's configuration data (dashboards, insights,
    feature flags, experiments, surveys, notebooks) with automatic access control
    based on the user's permissions.
    """

    name: str = "query_postgres"
    args_schema: type[BaseModel] = QueryPostgresToolArgs
    context_prompt_template: str = QUERY_POSTGRES_CONTEXT_PROMPT

    # This tool is read-only and doesn't require specific resource permissions
    # Access control is enforced at query execution time based on the data being queried

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
        description = """Execute HogQL queries against PostgreSQL tables containing PostHog configuration data.

Available tables: dashboard, insight, featureflag, experiment, survey, notebook, action

Security: Queries are automatically filtered by team and user access permissions.

Examples:
- SELECT name, description FROM dashboard ORDER BY created_at DESC LIMIT 10
- SELECT key, name, active FROM featureflag WHERE active = true
- SELECT name, start_date FROM experiment WHERE end_date IS NULL"""

        return cls(
            team=team,
            user=user,
            state=state,
            node_path=node_path,
            config=config,
            context_manager=context_manager,
            description=description,
        )

    async def _arun_impl(self, query: str) -> tuple[str, ToolMessagesArtifact | None]:
        """Execute the PostgreSQL query and return results."""
        try:
            result = execute_postgres_query(
                query=query,
                team=self._team,
                user=self._user,
                limit=100,  # Reasonable limit for AI agent queries
            )
        except QueryError as e:
            # Recoverable error - LLM can fix and retry
            return format_prompt_string(QUERY_POSTGRES_RECOVERABLE_ERROR_PROMPT, error=str(e)), None
        except Exception:
            # Log the error for debugging
            import structlog

            logger = structlog.get_logger(__name__)
            logger.exception(
                "Unexpected error executing PostgreSQL query",
                query=query,
                team_id=self._team.id,
                user_id=self._user.id,
            )
            return QUERY_POSTGRES_UNRECOVERABLE_ERROR_PROMPT, None

        # Format results for LLM consumption
        formatted_result = format_postgres_result_for_llm(result)

        # Build response message
        response_content = f"Query executed successfully. {result.row_count} rows returned."
        if result.truncated:
            response_content += " (Results truncated)"

        return formatted_result, ToolMessagesArtifact(
            messages=[
                AssistantToolCallMessage(
                    content=response_content,
                    id=str(uuid4()),
                    tool_call_id=self.tool_call_id,
                    ui_payload={
                        self.get_name(): {
                            "query": query,
                            "row_count": result.row_count,
                            "columns": result.columns,
                        }
                    },
                ),
            ]
        )
