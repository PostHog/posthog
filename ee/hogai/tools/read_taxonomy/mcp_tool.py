from django.db import OperationalError

from posthog.sync import database_sync_to_async
from posthog.taxonomy.property_definition_api import is_query_canceled

from ee.hogai.chat_agent.query_planner.toolkit import TaxonomyAgentToolkit
from ee.hogai.mcp_tool import MCPTool, mcp_tool_registry
from ee.hogai.tool_errors import MaxToolRetryableError, MaxToolTransientError

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
        toolkit = TaxonomyAgentToolkit(self._team, self._user, event_source=self._event_source)

        try:

            @database_sync_to_async(thread_sensitive=False)
            def _execute_query():
                return execute_taxonomy_query(
                    args.query, toolkit, self._team, self._user, event_source=self._event_source
                )

            return await _execute_query()
        except ValueError as e:
            raise MaxToolRetryableError(str(e))
        except OperationalError as e:
            # Only a statement cancelled by statement_timeout (SQLSTATE 57014) is worth a retry.
            # Let connection loss, shutdown, deadlocks, and the like reach the generic handler so
            # they are logged and captured instead of mislabeled as a timeout.
            if not is_query_canceled(e):
                raise
            # MaxToolError appends its own retry hint and a period, so this ends bare. The hint for
            # a transient error offers one unchanged retry, so do not suggest narrowing the read.
            raise MaxToolTransientError("Reading the taxonomy timed out. This can happen on large projects") from e
