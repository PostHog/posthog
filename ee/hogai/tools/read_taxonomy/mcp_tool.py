from django.db import OperationalError

from prometheus_client import Counter

from posthog.errors import QueryErrorCategory, classify_query_error
from posthog.sync import database_sync_to_async
from posthog.taxonomy.property_definition_api import is_query_canceled

from ee.hogai.chat_agent.query_planner.toolkit import TaxonomyAgentToolkit
from ee.hogai.mcp_tool import MCPTool, mcp_tool_registry
from ee.hogai.tool_errors import MaxToolError, MaxToolRetryableError, MaxToolTransientError

from .core import ReadTaxonomyToolArgs, describe_taxonomy_query, execute_taxonomy_query

READ_TAXONOMY_TIMED_OUT_COUNTER = Counter(
    "read_taxonomy_timed_out_total",
    "read_taxonomy reads cancelled by the statement timeout.",
    labelnames=["query_kind"],
)

READ_TAXONOMY_QUERY_FAILED_COUNTER = Counter(
    "read_taxonomy_query_failed_total",
    "read_taxonomy reads that failed in the query layer, by the category the caller was told.",
    labelnames=["query_kind", "category"],
)

# Categories a caller can act on. Anything outside this map is a real defect, so it stays on the
# generic path that logs and captures it rather than being dressed up as an expected failure.
_TRANSIENT_QUERY_CATEGORIES = frozenset(
    {
        QueryErrorCategory.RATE_LIMITED,
        QueryErrorCategory.QUERY_PERFORMANCE_ERROR,
        QueryErrorCategory.CANCELLED,
    }
)


def _classify_query_failure(error: Exception, subject: str) -> tuple[QueryErrorCategory, MaxToolError] | None:
    """Turn a query-layer failure into an error the caller can act on, or None if it is a defect.

    Every exception class reachable here carries a message written for the end user, so quoting it
    leaks nothing about the query PostHog ran. MaxToolError appends its own retry hint and a period,
    so each message ends bare.
    """
    category = classify_query_error(error)

    if category in _TRANSIENT_QUERY_CATEGORIES:
        return category, MaxToolTransientError(f"Reading {subject} failed while the query ran: {error}")
    if category == QueryErrorCategory.USER_ERROR:
        return category, MaxToolRetryableError(f"Reading {subject} failed: {error}")
    return None


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
        subject = describe_taxonomy_query(args.query)

        try:

            @database_sync_to_async(thread_sensitive=False)
            def _execute_query():
                return execute_taxonomy_query(
                    args.query, toolkit, self._team, self._user, event_source=self._event_source
                )

            return await _execute_query()
        except ValueError as e:
            raise MaxToolRetryableError(f"Reading {subject} failed: {e}")
        except OperationalError as e:
            # Only a statement cancelled by statement_timeout (SQLSTATE 57014) is worth a retry.
            # Let connection loss, shutdown, deadlocks, and the like reach the generic handler so
            # they are logged and captured instead of mislabeled as a timeout.
            if not is_query_canceled(e):
                raise
            # The MCP transport answers a MaxToolError without logging or capturing it, so a timeout
            # that reaches the caller as one leaves no trace. Count it here, or the rate this change
            # is meant to drive to zero becomes unmeasurable the moment it stops being an exception.
            READ_TAXONOMY_TIMED_OUT_COUNTER.labels(query_kind=args.query.kind).inc()
            # MaxToolError appends its own retry hint and a period, so this ends bare. The hint for
            # a transient error offers one unchanged retry, so do not suggest narrowing the read.
            raise MaxToolTransientError(f"Reading {subject} timed out. This can happen on large projects") from e
        except Exception as e:
            # ClickHouse capacity, memory, and cancellation errors dominate this path. They are
            # transient and safe to retry, so telling the caller "internal error, do not retry"
            # threw away a read that a second attempt would have served.
            classified = _classify_query_failure(e, subject)
            if classified is None:
                raise
            category, tool_error = classified
            READ_TAXONOMY_QUERY_FAILED_COUNTER.labels(query_kind=args.query.kind, category=category).inc()
            raise tool_error from e
