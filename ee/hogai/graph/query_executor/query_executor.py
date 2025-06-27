from datetime import datetime
from typing import Optional

from ee.hogai.graph.query_executor.format import (
    FunnelResultsFormatter,
    RetentionResultsFormatter,
    SQLResultsFormatter,
    TrendsResultsFormatter,
)
from posthog.clickhouse.query_tagging import tags_context, Product
from posthog.models.team.team import Team
from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
    TrendsQuery,
    FunnelsQuery,
    RetentionQuery,
    HogQLQuery,
)
from django.conf import settings
from posthog.api.services.query import process_query_dict
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.clickhouse.client.execute_async import get_query_status
from rest_framework.exceptions import APIException
from posthog.errors import ExposedCHQueryError
from posthog.hogql.errors import ExposedHogQLError, NotImplementedError as HogQLNotImplementedError
from time import sleep
import json
from django.core.serializers.json import DjangoJSONEncoder

SupportedQueryTypes = (
    AssistantTrendsQuery
    | TrendsQuery
    | AssistantFunnelsQuery
    | FunnelsQuery
    | AssistantRetentionQuery
    | RetentionQuery
    | AssistantHogQLQuery
    | HogQLQuery
)


class AssistantQueryExecutor:
    """
    Reusable class for executing queries and formatting results for the AI assistant.

    This class handles the complete query lifecycle:
    - Executes queries using the appropriate execution mode
    - Handles async query polling when needed
    - Formats results using query-specific formatters
    - Provides fallback error handling and result compression

    Can be used by QueryExecutorNode and other components that need to run and format queries
    for AI assistant responses.

    Attributes:
        _team: The PostHog team context for query execution
        _utc_now_datetime: Current UTC datetime for time-based calculations
    """

    def __init__(self, team: Team, utc_now_datetime: datetime):
        self._team = team
        self._utc_now_datetime = utc_now_datetime

    def run_and_format_query(
        self, query: SupportedQueryTypes, execution_mode: Optional[ExecutionMode] = None
    ) -> tuple[str, bool]:  # noqa: F821
        """
        Run a query and format the results with detailed fallback information.

        Args:
            query: The query object (AssistantTrendsQuery, AssistantFunnelsQuery, etc.)
            execution_mode: Optional execution mode override. If None, defaults to:
                          - RECENT_CACHE_CALCULATE_ASYNC_IF_STALE in production
                          - CALCULATE_BLOCKING_ALWAYS in tests

        Returns:
            Tuple of (formatted results as string, whether fallback was used)
            - formatted results: Query results formatted for AI consumption
            - fallback used: True if JSON fallback was used due to formatting errors

        Raises:
            Exception: If query execution fails with descriptive error messages
        """
        with tags_context(product=Product.MAX_AI, team_id=self._team.pk, org_id=self._team.organization_id):
            response_dict = self._execute_query(query, execution_mode)

        try:
            # Attempt to format results using query-specific formatters
            formatted_results = self._compress_results(query, response_dict)
            return formatted_results, False  # No fallback used
        except Exception as err:
            if isinstance(err, NotImplementedError):
                # Re-raise NotImplementedError for unsupported query types
                raise
            # Fallback to raw JSON if formatting fails - ensures robustness
            fallback_results = json.dumps(response_dict["results"], cls=DjangoJSONEncoder, separators=(",", ":"))
            return fallback_results, True  # Fallback was used

    def _execute_query(self, query: SupportedQueryTypes, execution_mode: Optional[ExecutionMode] = None) -> dict:
        """
        Execute a query and return the response dict.

        Args:
            query: The query object
            execution_mode: Optional execution mode override

        Returns:
            Response dict with query results

        Raises:
            Exception: If query execution fails
        """
        # Set appropriate execution mode based on environment
        if execution_mode is None:
            execution_mode = (
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE
                if not settings.TEST
                else ExecutionMode.CALCULATE_BLOCKING_ALWAYS
            )

        try:
            # Execute the query using PostHog's query processing system
            results_response = process_query_dict(
                self._team,
                query.model_dump(mode="json"),
                execution_mode=execution_mode,
            )

            # Normalize response to dict format for consistent handling
            if isinstance(results_response, dict):
                response_dict = results_response
            else:
                response_dict = results_response.model_dump(mode="json")

            # Handle async queries that may need polling
            if query_status := response_dict.get("query_status"):
                if not query_status["complete"]:
                    # Poll async query until completion with exponential backoff
                    # Total wait time: ~726 seconds with 100ms increments
                    for wait_ms in range(100, 12000, 100):
                        sleep(wait_ms / 1000)
                        query_status = get_query_status(team_id=self._team.pk, query_id=query_status["id"]).model_dump(
                            mode="json"
                        )
                        if query_status["complete"]:
                            break
                    else:
                        # Query timed out after maximum wait time
                        raise APIException(
                            "Query hasn't completed in time. It's worth trying again, maybe with a shorter time range."
                        )

                # Check for query execution errors before using results
                if query_status.get("error"):
                    if error_message := query_status.get("error_message"):
                        raise APIException(error_message)
                    raise Exception("Query failed")

                # Use the completed query results
                response_dict = query_status["results"]

        except (APIException, ExposedHogQLError, HogQLNotImplementedError, ExposedCHQueryError) as err:
            # Handle known query execution errors with user-friendly messages
            err_message = str(err)
            if isinstance(err, APIException):
                if isinstance(err.detail, dict):
                    err_message = ", ".join(f"{key}: {value}" for key, value in err.detail.items())
                elif isinstance(err.detail, list):
                    err_message = ", ".join(map(str, err.detail))
            raise Exception(f"There was an error running this query: {err_message}")
        except Exception:
            # Catch-all for unexpected errors during query execution
            raise Exception("There was an unknown error running this query.")

        return response_dict

    def _compress_results(self, query: SupportedQueryTypes, response: dict) -> str:
        """
        Format query results using appropriate formatter based on query type.

        Args:
            query: The query object to determine formatting approach
            response: Raw query response dict containing results and metadata

        Returns:
            Formatted results as a string optimized for AI assistant consumption

        Raises:
            NotImplementedError: If the query type is not supported
        """
        # Handle assistant-specific query types with direct formatting
        if isinstance(query, AssistantTrendsQuery | TrendsQuery):
            return TrendsResultsFormatter(query, response["results"]).format()
        elif isinstance(query, AssistantFunnelsQuery | FunnelsQuery):
            return FunnelResultsFormatter(query, response["results"], self._team, self._utc_now_datetime).format()
        elif isinstance(query, AssistantRetentionQuery | RetentionQuery):
            return RetentionResultsFormatter(query, response["results"]).format()
        elif isinstance(query, AssistantHogQLQuery | HogQLQuery):
            return SQLResultsFormatter(query, response["results"], response["columns"]).format()
