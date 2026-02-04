from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from ee.hogai.chat_agent.query_planner.toolkit import TaxonomyAgentToolkit
from ee.hogai.external_tool import ExternalTool, ExternalToolResult, register_external_tool

from .core import ReadTaxonomyToolArgs, execute_taxonomy_query


@register_external_tool
class ReadTaxonomyExternalTool(ExternalTool):
    """
    External version of ReadTaxonomyTool for API/MCP callers.

    Explores the user's taxonomy (events, actions, properties, and property values).
    """

    name = "read_taxonomy"
    args_schema = ReadTaxonomyToolArgs

    async def execute(self, team: Team, user: User, query: dict | None = None, **kwargs) -> ExternalToolResult:
        try:
            validated_args = ReadTaxonomyToolArgs(query=query)
            validated_query = validated_args.query
        except Exception as e:
            return ExternalToolResult(
                success=False,
                content=f"Invalid query: {e}",
                error="validation_error",
            )

        toolkit = TaxonomyAgentToolkit(team)

        try:

            @database_sync_to_async(thread_sensitive=False)
            def _execute_query():
                return execute_taxonomy_query(validated_query, toolkit, team)

            res = await _execute_query()
            return ExternalToolResult(
                success=True,
                content=res,
                data={"query": query},
            )
        except ValueError as e:
            return ExternalToolResult(
                success=False,
                content=str(e),
                error="validation_error",
            )
        except Exception as e:
            return ExternalToolResult(
                success=False,
                content=f"Failed to read taxonomy: {e}",
                error="execution_error",
            )
