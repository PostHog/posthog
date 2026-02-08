from posthog.sync import database_sync_to_async

from ee.hogai.chat_agent.query_planner.toolkit import TaxonomyAgentToolkit
from ee.hogai.mcp_tool import MCPTool, mcp_tool_registry
from ee.hogai.tool_errors import MaxToolRetryableError

from .core import ReadTaxonomyToolArgs, execute_taxonomy_query


@mcp_tool_registry.register(scopes=["action:read", "property_definition:read", "event_definition:read"])
class ReadTaxonomyMCPTool(MCPTool[ReadTaxonomyToolArgs]):
    """
    MCP version of ReadTaxonomyTool.

    Explores the user's taxonomy (events, actions, properties, and property values).
    """

    name = "read_taxonomy"
    args_schema = ReadTaxonomyToolArgs

    async def execute(self, args: ReadTaxonomyToolArgs) -> str:
        toolkit = TaxonomyAgentToolkit(self._team)

        try:

            @database_sync_to_async(thread_sensitive=False)
            def _execute_query():
                return execute_taxonomy_query(args.query, toolkit, self._team)

            return await _execute_query()
        except ValueError as e:
            raise MaxToolRetryableError(str(e))
