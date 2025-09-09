import json
import time
from datetime import datetime
from time import sleep
from typing import Optional

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder

import structlog
from rest_framework.exceptions import APIException

from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
    FunnelsQuery,
    HogQLQuery,
    RetentionQuery,
    TrendsQuery,
)

from posthog.hogql.errors import (
    ExposedHogQLError,
    NotImplementedError as HogQLNotImplementedError,
)

from posthog.api.services.query import process_query_dict
from posthog.clickhouse.client.execute_async import get_query_status
from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.errors import ExposedCHQueryError
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from ee.hogai.graph.query_executor.format import (
    FunnelResultsFormatter,
    RetentionResultsFormatter,
    SQLResultsFormatter,
    TrendsResultsFormatter,
)

logger = structlog.get_logger(__name__)

TIMING_LOG_PREFIX = "[QUERY_EXECUTOR]"

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
        self,
        query: SupportedQueryTypes,
        execution_mode: Optional[ExecutionMode] = None,
        insight_id=None,
        debug_timing=False,
    ) -> tuple[str, bool]:
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
        start_time = time.time()
        query_type = type(query).__name__
        if debug_timing:
            logger.warning(f"{TIMING_LOG_PREFIX} Starting run_and_format_query for {query_type}")

        try:
            with tags_context(product=Product.MAX_AI, team_id=self._team.pk, org_id=self._team.organization_id):
                if insight_id:
                    # Including insight ID for insight search
                    tag_queries(insight_id=insight_id)
                execute_start = time.time()
                response_dict = self.execute_query(query, execution_mode, debug_timing=debug_timing)
                execute_elapsed = time.time() - execute_start
                if debug_timing:
                    logger.warning(f"{TIMING_LOG_PREFIX} execute_query completed in {execute_elapsed:.3f}s")

            try:
                # Attempt to format results using query-specific formatters
                format_start = time.time()
                formatted_results = self._compress_results(query, response_dict, debug_timing=debug_timing)
                format_elapsed = time.time() - format_start
                total_elapsed = time.time() - start_time
                if debug_timing:
                    logger.warning(
                        f"{TIMING_LOG_PREFIX} _compress_results completed in {format_elapsed:.3f}s, "
                        f"total run_and_format_query: {total_elapsed:.3f}s"
                    )
                return formatted_results, False  # No fallback used
            except Exception as err:
                if isinstance(err, NotImplementedError):
                    # Re-raise NotImplementedError for unsupported query types
                    raise
                # Fallback to raw JSON if formatting fails - ensures robustness
                fallback_start = time.time()
                fallback_results = json.dumps(response_dict["results"], cls=DjangoJSONEncoder, separators=(",", ":"))
                fallback_elapsed = time.time() - fallback_start
                total_elapsed = time.time() - start_time
                if debug_timing:
                    logger.warning(
                        f"{TIMING_LOG_PREFIX} Fallback JSON formatting completed in {fallback_elapsed:.3f}s, "
                        f"total with fallback: {total_elapsed:.3f}s"
                    )
                return fallback_results, True  # Fallback was used
        except Exception:
            elapsed = time.time() - start_time
            if debug_timing:
                logger.exception(f"{TIMING_LOG_PREFIX} run_and_format_query failed after {elapsed:.3f}s")
            raise

    @database_sync_to_async(thread_sensitive=False)
    def arun_and_format_query(
        self, query: SupportedQueryTypes, execution_mode: Optional[ExecutionMode] = None, debug_timing=False
    ) -> tuple[str, bool]:
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
        start_time = time.time()
        query_type = type(query).__name__
        if debug_timing:
            logger.warning(f"{TIMING_LOG_PREFIX} [ASYNC->SYNC] Starting arun_and_format_query for {query_type}")

        try:
            sync_start = time.time()
            result = self.run_and_format_query(query, execution_mode, debug_timing=debug_timing)
            sync_elapsed = time.time() - sync_start
            total_elapsed = time.time() - start_time

            if debug_timing:
                logger.warning(
                    f"{TIMING_LOG_PREFIX} [ASYNC->SYNC] Sync execution took {sync_elapsed:.3f}s, "
                    f"async wrapper overhead: {(total_elapsed - sync_elapsed) * 1000:.1f}ms, "
                    f"total: {total_elapsed:.3f}s"
                )
            return result
        except Exception:
            elapsed = time.time() - start_time
            if debug_timing:
                logger.exception(f"{TIMING_LOG_PREFIX} [ASYNC->SYNC] arun_and_format_query failed after {elapsed:.3f}s")
            raise

    def execute_query(
        self, query: SupportedQueryTypes, execution_mode: Optional[ExecutionMode] = None, debug_timing=False
    ) -> dict:
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
        start_time = time.time()
        query_type = type(query).__name__

        # Set appropriate execution mode based on environment
        if execution_mode is None:
            execution_mode = (
                ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE
                if not settings.TEST
                else ExecutionMode.CALCULATE_BLOCKING_ALWAYS
            )

        if debug_timing:
            logger.warning(
                f"{TIMING_LOG_PREFIX} Starting execute_query for {query_type} with mode {execution_mode.value}"
            )

        try:
            # Execute the query using PostHog's query processing system
            process_start = time.time()
            if debug_timing:
                logger.warning(f"{TIMING_LOG_PREFIX} Calling process_query_dict")

            results_response = process_query_dict(
                self._team,
                query.model_dump(mode="json"),
                execution_mode=execution_mode,
            )

            process_elapsed = time.time() - process_start
            if debug_timing:
                logger.warning(f"{TIMING_LOG_PREFIX} process_query_dict completed in {process_elapsed:.3f}s")

            # Normalize response to dict format for consistent handling
            if isinstance(results_response, dict):
                response_dict = results_response
            else:
                response_dict = results_response.model_dump(mode="json")

            # Handle async queries that may need polling
            if query_status := response_dict.get("query_status"):
                if not query_status["complete"]:
                    polling_start = time.time()
                    poll_count = 0
                    total_wait_ms = 0

                    if debug_timing:
                        logger.warning(
                            f"{TIMING_LOG_PREFIX} Query returned incomplete, starting async polling (query_id={query_status['id']})"
                        )

                    # Poll async query until completion with exponential backoff
                    # Total wait time: ~726 seconds with 100ms increments
                    for wait_ms in range(100, 12000, 100):
                        poll_count += 1
                        total_wait_ms += wait_ms

                        if poll_count % 10 == 0 and debug_timing:  # Log every 10 polls
                            logger.warning(
                                f"{TIMING_LOG_PREFIX} Polling attempt {poll_count}, total wait: {total_wait_ms/1000:.1f}s"
                            )

                        sleep(wait_ms / 1000)

                        status_check_start = time.time()
                        query_status = get_query_status(team_id=self._team.pk, query_id=query_status["id"]).model_dump(
                            mode="json"
                        )
                        status_check_elapsed = time.time() - status_check_start

                        if status_check_elapsed > 0.5 and debug_timing:  # Log slow status checks
                            logger.warning(f"{TIMING_LOG_PREFIX} Slow status check: {status_check_elapsed:.3f}s")

                        if query_status["complete"]:
                            polling_elapsed = time.time() - polling_start
                            if debug_timing:
                                logger.warning(
                                    f"{TIMING_LOG_PREFIX} Async query completed after {poll_count} polls, "
                                    f"total polling time: {polling_elapsed:.3f}s"
                                )
                            break
                    else:
                        # Query timed out after maximum wait time
                        polling_elapsed = time.time() - polling_start
                        if debug_timing:
                            logger.error(
                                f"{TIMING_LOG_PREFIX} Query timeout after {poll_count} polls, {polling_elapsed:.3f}s"
                            )
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
            elapsed = time.time() - start_time
            # Handle known query execution errors with user-friendly messages
            err_message = str(err)
            if isinstance(err, APIException):
                if isinstance(err.detail, dict):
                    err_message = ", ".join(f"{key}: {value}" for key, value in err.detail.items())
                elif isinstance(err.detail, list):
                    err_message = ", ".join(map(str, err.detail))
            if debug_timing:
                logger.exception(f"{TIMING_LOG_PREFIX} Query execution failed after {elapsed:.3f}s: {err_message}")
            raise Exception(f"There was an error running this query: {err_message}")
        except Exception:
            elapsed = time.time() - start_time
            # Catch-all for unexpected errors during query execution
            if debug_timing:
                logger.exception(f"{TIMING_LOG_PREFIX} Unknown error during query execution after {elapsed:.3f}s")
            raise Exception("There was an unknown error running this query.")

        total_elapsed = time.time() - start_time
        if debug_timing:
            logger.warning(f"{TIMING_LOG_PREFIX} execute_query completed successfully in {total_elapsed:.3f}s")
        return response_dict

    def _compress_results(self, query: SupportedQueryTypes, response: dict, debug_timing=False) -> str:
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
        start_time = time.time()
        query_type = type(query).__name__
        formatter_name = None

        try:
            # Handle assistant-specific query types with direct formatting
            if isinstance(query, AssistantTrendsQuery | TrendsQuery):
                formatter_name = "TrendsResultsFormatter"
                result = TrendsResultsFormatter(query, response["results"]).format()
            elif isinstance(query, AssistantFunnelsQuery | FunnelsQuery):
                formatter_name = "FunnelResultsFormatter"
                result = FunnelResultsFormatter(query, response["results"], self._team, self._utc_now_datetime).format()
            elif isinstance(query, AssistantRetentionQuery | RetentionQuery):
                formatter_name = "RetentionResultsFormatter"
                result = RetentionResultsFormatter(query, response["results"]).format()
            elif isinstance(query, AssistantHogQLQuery | HogQLQuery):
                formatter_name = "SQLResultsFormatter"
                result = SQLResultsFormatter(query, response["results"], response["columns"]).format()
            else:
                raise NotImplementedError(f"Unsupported query type: {query_type}")

            elapsed = time.time() - start_time
            if debug_timing:
                logger.warning(
                    f"{TIMING_LOG_PREFIX} {formatter_name}.format() completed in {elapsed:.3f}s for {query_type}"
                )
            return result
        except Exception:
            elapsed = time.time() - start_time
            if debug_timing:
                logger.exception(f"{TIMING_LOG_PREFIX} _compress_results failed after {elapsed:.3f}s for {query_type}")
            raise
