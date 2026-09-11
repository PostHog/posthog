import json
import time
import asyncio
from dataclasses import field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Optional

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync
from posthoganalytics import capture_exception
from pydantic import BaseModel
from rest_framework.exceptions import APIException

from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantLifecycleQuery,
    AssistantPathsQuery,
    AssistantRetentionQuery,
    AssistantStickinessQuery,
    AssistantTrendsQuery,
    ChartDisplayType,
    DataVisualizationNode,
    FunnelsQuery,
    FunnelVizType,
    HogQLQuery,
    LifecycleQuery,
    PathsQuery,
    QueryScanStatus,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
)

from posthog.hogql.constants import LimitContext
from posthog.hogql.errors import (
    ExposedHogQLError,
    NotImplementedError as HogQLNotImplementedError,
)

from posthog.api.services.query import process_query_dict
from posthog.clickhouse.client.execute_async import get_query_status
from posthog.clickhouse.query_tagging import Feature, Product, get_query_tags, tag_queries, tags_context
from posthog.dataclasses import frozen
from posthog.errors import ExposedCHQueryError
from posthog.event_usage import EventSource
from posthog.hogql_queries.query_runner import BLOCKING_EXECUTION_MODES, ExecutionMode
from posthog.models import Team
from posthog.query_scan.flag import QueryScanFlag, get_query_scan_flag
from posthog.query_scan.slot import (
    QueryScanSlot,
    get as get_query_scan_slot,
)
from posthog.sync import database_sync_to_async

from products.access_control.backend.facade.user_access_control import UserAccessControlError

from ee.hogai.context.insight.format import (
    NULL_MARKER,
    TRUNCATED_MARKER,
    BoxPlotResultsFormatter,
    FunnelResultsFormatter,
    LifecycleResultsFormatter,
    PathsResultsFormatter,
    RetentionResultsFormatter,
    SQLResultsFormatter,
    StickinessResultsFormatter,
    TrendsResultsFormatter,
    format_access_control_warnings,
    format_query_scan_warnings,
    format_warehouse_sync_warnings,
    get_boxplot_results,
    is_boxplot_query,
)
from ee.hogai.tool_errors import MaxToolRetryableError
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.query import validate_assistant_query
from ee.hogai.utils.types.base import AnyAssistantGeneratedQuery, AnyPydanticModelQuery

if TYPE_CHECKING:
    from posthog.models import User

from .prompts import (
    BOX_PLOT_EXAMPLE_PROMPT,
    FALLBACK_EXAMPLE_PROMPT,
    FUNNEL_STEPS_EXAMPLE_PROMPT,
    FUNNEL_TIME_TO_CONVERT_EXAMPLE_PROMPT,
    FUNNEL_TRENDS_EXAMPLE_PROMPT,
    LIFECYCLE_EXAMPLE_PROMPT,
    PATHS_EXAMPLE_PROMPT,
    QUERY_RESULTS_PROMPT,
    RETENTION_EXAMPLE_PROMPT,
    SQL_EXAMPLE_PROMPT,
    STICKINESS_EXAMPLE_PROMPT,
    TRENDS_EXAMPLE_PROMPT,
)

logger = structlog.get_logger(__name__)

TIMING_LOG_PREFIX = "[QUERY_EXECUTOR]"


@frozen
class FormattedQueryResult:
    formatted: str
    fallback_used: bool
    response: dict = field(repr=False)


def is_supported_query(query: AnyPydanticModelQuery | AnyAssistantGeneratedQuery) -> bool:
    return isinstance(
        query,
        AssistantTrendsQuery
        | TrendsQuery
        | AssistantFunnelsQuery
        | FunnelsQuery
        | AssistantLifecycleQuery
        | LifecycleQuery
        | AssistantPathsQuery
        | PathsQuery
        | AssistantStickinessQuery
        | StickinessQuery
        | LifecycleQuery
        | AssistantRetentionQuery
        | RetentionQuery
        | AssistantHogQLQuery
        | HogQLQuery
        | DataVisualizationNode,
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

    WAIT_TIME_S = 0.5
    SCAN_POLL_INTERVAL_S = 0.5
    SCAN_POLL_TIMEOUT_S = 5.0

    def __init__(
        self,
        team: Team,
        utc_now_datetime: datetime,
        user: "User",
        event_source: EventSource = EventSource.POSTHOG_AI,
    ):
        self._team = team
        self._utc_now_datetime = utc_now_datetime
        self._user = user
        self._event_source = event_source

    async def arun_format_and_capture(
        self,
        query: AnyPydanticModelQuery | AnyAssistantGeneratedQuery,
        execution_mode: Optional[ExecutionMode] = None,
        insight_id=None,
        debug_timing=False,
        truncate_results: bool = True,
    ) -> FormattedQueryResult:
        """
        Run a query and format the results with detailed fallback information.

        Args:
            query: The query object (AssistantTrendsQuery, AssistantFunnelsQuery, etc.)
            execution_mode: Optional execution mode override. If None, defaults to:
                          - RECENT_CACHE_CALCULATE_ASYNC_IF_STALE in production
                          - CALCULATE_BLOCKING_ALWAYS in tests

        Returns:
            A FormattedQueryResult carrying the formatted text, whether the JSON fallback was
            used, and the raw response for callers that need the columns and rows themselves.

        Raises:
            Exception: If query execution fails with descriptive error messages
        """
        start_time = time.time()
        query_type = type(query).__name__
        if debug_timing:
            logger.warning(f"{TIMING_LOG_PREFIX} Starting arun_format_and_capture for {query_type}")

        try:
            active_tags = get_query_tags()
            with tags_context(
                product=Product.MAX_AI,
                feature=active_tags.feature or Feature.POSTHOG_AI,
                team_id=self._team.pk,
                org_id=self._team.organization_id,
            ):
                if insight_id:
                    # Including insight ID for insight search
                    tag_queries(insight_id=insight_id)
                execute_start = time.time()
                response_dict = await self.aexecute_query(query, execution_mode, debug_timing=debug_timing)
                execute_elapsed = time.time() - execute_start
                if debug_timing:
                    logger.warning(f"{TIMING_LOG_PREFIX} aexecute_query completed in {execute_elapsed:.3f}s")

            # A caller that takes the raw response never renders the findings, so waiting there would only
            # delay the reply.
            if isinstance(response_dict, dict):
                await self._await_query_scan(response_dict)

            try:
                # Attempt to format results using query-specific formatters
                format_start = time.time()
                formatted_results = await self._compress_results(
                    query, response_dict, debug_timing=debug_timing, truncate_results=truncate_results
                )
                format_elapsed = time.time() - format_start
                total_elapsed = time.time() - start_time
                if debug_timing:
                    logger.warning(
                        f"{TIMING_LOG_PREFIX} _compress_results completed in {format_elapsed:.3f}s, "
                        f"total arun_format_and_capture: {total_elapsed:.3f}s"
                    )
                return FormattedQueryResult(formatted=formatted_results, fallback_used=False, response=response_dict)
            except Exception as err:
                if not isinstance(err, NotImplementedError):
                    capture_exception(err, properties={"tag": "max_ai"})
                # Fallback to raw JSON if formatting fails - ensures robustness
                fallback_start = time.time()
                fallback_results = self._warning_prefix(response_dict) + json.dumps(
                    response_dict["results"], cls=DjangoJSONEncoder, separators=(",", ":")
                )
                fallback_elapsed = time.time() - fallback_start
                total_elapsed = time.time() - start_time
                if debug_timing:
                    logger.warning(
                        f"{TIMING_LOG_PREFIX} Fallback JSON formatting completed in {fallback_elapsed:.3f}s, "
                        f"total with fallback: {total_elapsed:.3f}s"
                    )
                return FormattedQueryResult(formatted=fallback_results, fallback_used=True, response=response_dict)
        except Exception:
            elapsed = time.time() - start_time
            if debug_timing:
                logger.exception(f"{TIMING_LOG_PREFIX} arun_format_and_capture failed after {elapsed:.3f}s")
            raise

    async def arun_and_format_query(
        self,
        query: AnyPydanticModelQuery | AnyAssistantGeneratedQuery,
        execution_mode: Optional[ExecutionMode] = None,
        insight_id=None,
        debug_timing=False,
        truncate_results: bool = True,
    ) -> tuple[str, bool]:
        result = await self.arun_format_and_capture(
            query,
            execution_mode,
            insight_id=insight_id,
            debug_timing=debug_timing,
            truncate_results=truncate_results,
        )
        return result.formatted, result.fallback_used

    @async_to_sync
    async def run_and_format_query(
        self,
        query: AnyPydanticModelQuery | AnyAssistantGeneratedQuery,
        execution_mode: Optional[ExecutionMode] = None,
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
            logger.warning(f"{TIMING_LOG_PREFIX} [SYNC->ASYNC] Starting arun_and_format_query for {query_type}")

        try:
            sync_start = time.time()
            result = await self.arun_and_format_query(query, execution_mode, debug_timing=debug_timing)
            sync_elapsed = time.time() - sync_start
            total_elapsed = time.time() - start_time

            if debug_timing:
                logger.warning(
                    f"{TIMING_LOG_PREFIX} [SYNC->ASYNC] Sync execution took {sync_elapsed:.3f}s, "
                    f"async wrapper overhead: {(total_elapsed - sync_elapsed) * 1000:.1f}ms, "
                    f"total: {total_elapsed:.3f}s"
                )
            return result
        except Exception:
            elapsed = time.time() - start_time
            if debug_timing:
                logger.exception(f"{TIMING_LOG_PREFIX} [SYNC->ASYNC] arun_and_format_query failed after {elapsed:.3f}s")
            raise

    async def aexecute_query(
        self,
        query: AnyPydanticModelQuery | AnyAssistantGeneratedQuery,
        execution_mode: Optional[ExecutionMode] = None,
        debug_timing=False,
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
                f"{TIMING_LOG_PREFIX} Starting aexecute_query for {query_type} with mode {execution_mode.value}"
            )

        try:
            # Execute the query using PostHog's query processing system
            process_start = time.time()
            if debug_timing:
                logger.warning(f"{TIMING_LOG_PREFIX} Calling process_query_dict")

            # Snapshot the caller's query tags from the async context so we can replay them inside
            # the threaded sync function — `database_sync_to_async` crosses a thread boundary and
            # downstream code (e.g. `enqueue_process_query_task`) reads `get_query_tags()` from the
            # executing thread to forward to Celery, where contextvars do not propagate.
            parent_tag_kwargs = get_query_tags().model_dump(exclude_none=True)
            team = self._team
            user = self._user
            event_source = self._event_source
            query_dict = query.model_dump(mode="json")

            def process_query_dict_with_tags() -> dict | BaseModel:
                with tags_context(**parent_tag_kwargs):
                    return process_query_dict(
                        team,
                        query_dict,
                        execution_mode=execution_mode,
                        limit_context=LimitContext.POSTHOG_AI,
                        user=user,
                        analytics_props={"source": event_source},
                    )

            # If the query has a blocking execution, execute on a separate thread. Otherwise, use the main thread
            # as it only does lightweight ORM retrievals and Redis calls. If we run in tests, do not spawn another thread.
            results_response = await database_sync_to_async(
                process_query_dict_with_tags, thread_sensitive=execution_mode not in BLOCKING_EXECUTION_MODES
            )()

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
                    total_wait_s = 0.0

                    if debug_timing:
                        logger.warning(
                            f"{TIMING_LOG_PREFIX} Query returned incomplete, starting async polling (query_id={query_status['id']})"
                        )

                    # Poll async query until completion
                    # Total wait time: 5 minutes with linear increments
                    while total_wait_s <= 60 * 5:
                        poll_count += 1
                        total_wait_s += self.WAIT_TIME_S

                        if poll_count % 10 == 0 and debug_timing:  # Log every 10 polls
                            logger.warning(
                                f"{TIMING_LOG_PREFIX} Polling attempt {poll_count}, total wait: {total_wait_s:.1f}s"
                            )

                        await asyncio.sleep(self.WAIT_TIME_S)  # wait in seconds

                        status_check_start = time.time()
                        # Fast operation–Redis access
                        query_status_res = await database_sync_to_async(get_query_status, thread_sensitive=True)(
                            team_id=self._team.pk, query_id=query_status["id"]
                        )
                        status_check_elapsed = time.time() - status_check_start
                        total_wait_s += status_check_elapsed

                        query_status = query_status_res.model_dump(mode="json")

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

        except (
            APIException,
            ExposedHogQLError,
            HogQLNotImplementedError,
            ExposedCHQueryError,
            UserAccessControlError,
        ) as err:
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
            # `MaxToolError.to_summary` caps the message at 500 characters, so the failure the
            # agent has to act on goes first and the scan block takes whatever room is left.
            scan_block = await self._query_scan_block_for_error(err)
            raise MaxToolRetryableError(f"{err_message}\n\n{scan_block}" if scan_block else err_message)
        except Exception as err:
            elapsed = time.time() - start_time
            # Catch-all for unexpected errors during query execution. Surface the underlying error
            # text (truncated) so callers can diagnose the failure instead of an opaque message —
            # e.g. an invalid-UTF-8 encoding error points straight at substringUTF8().
            if debug_timing:
                logger.exception(f"{TIMING_LOG_PREFIX} Unknown error during query execution after {elapsed:.3f}s")
            err_message = str(err).strip() or repr(err)
            max_len = 500
            if len(err_message) > max_len:
                err_message = err_message[:max_len] + "… (truncated)"
            raise Exception(f"There was an unknown error running this query: {err_message}")

        # A failed query can come back as a structurally-valid response that carries an `error`
        # field and empty `results` instead of raising — e.g. a direct-SQL adapter statement
        # timeout (`_execute_direct_sql_query` stores `result.error`), or a ClickHouse error
        # captured in debug mode. Without this guard that response is formatted as a header-only
        # table, indistinguishable from "zero rows matched". Surface it as an error, mirroring the
        # `query_status.error` check the async-polling branch above already does.
        if isinstance(response_dict, dict) and (error := response_dict.get("error")):
            raise MaxToolRetryableError(str(error))

        total_elapsed = time.time() - start_time
        if debug_timing:
            logger.warning(f"{TIMING_LOG_PREFIX} aexecute_query completed successfully in {total_elapsed:.3f}s")
        return response_dict

    def _query_scan_poll_flag(self, scan: dict[str, Any]) -> QueryScanFlag | None:
        """The flag to poll this run's analysis under, or None when waiting cannot change the reply: no
        analysis is coming, or the mode hides it. The thresholds go with the read so a slot from other
        ratios is not served.
        """
        if scan.get("status") != QueryScanStatus.PENDING:
            return None
        flag = get_query_scan_flag(self._team)
        if flag is None or flag.mode != "show":
            return None
        return flag

    async def _await_query_scan(self, response: dict) -> None:
        """Wait for a slow run's analysis so its findings reach the same reply as the results. A failure
        costs the advice, never the results.
        """
        try:
            scan = response.get("query_scan")
            if not isinstance(scan, dict):
                return
            flag = self._query_scan_poll_flag(scan)
            if flag is None:
                return
            cache_key = response.get("cache_key")
            if not isinstance(cache_key, str):
                return
            slot = await self._poll_query_scan_slot(cache_key, flag.thresholds_fingerprint)
            if slot is None:
                return
            scan["status"] = str(slot.status)
            scan["range_share"] = slot.range_share
            scan["project_share"] = slot.project_share
            scan["killed"] = slot.killed
            response["warnings"] = [
                *(response.get("warnings") or []),
                *(finding.model_dump(by_alias=True, exclude_none=True) for finding in slot.findings),
            ]
        except Exception:
            logger.warning(f"{TIMING_LOG_PREFIX} query scan poll failed", exc_info=True)

    async def _poll_query_scan_slot(self, cache_key: str, thresholds: str) -> QueryScanSlot | None:
        deadline = time.monotonic() + self.SCAN_POLL_TIMEOUT_S
        while time.monotonic() < deadline:
            await asyncio.sleep(self.SCAN_POLL_INTERVAL_S)
            # Redis, not Postgres, but it blocks the same way, so keep it off the event loop.
            slot = await database_sync_to_async(get_query_scan_slot, thread_sensitive=True)(
                self._team.pk, cache_key, thresholds=thresholds
            )
            if slot is not None and slot.status == QueryScanStatus.DONE:
                return slot
        return None

    async def _query_scan_block_for_error(self, error: Exception) -> str:
        """The scan block for a run ClickHouse stopped, from the scan the runner put on the exception. Every
        retry dies the same way, so this reply is the only place to say what to change.
        """
        try:
            scan = getattr(error, "query_scan", None)
            cache_key = getattr(error, "cache_key", None)
            if not isinstance(scan, dict) or not isinstance(cache_key, str):
                return ""
            response: dict[str, Any] = {"query_scan": dict(scan), "warnings": []}
            flag = self._query_scan_poll_flag(scan)
            if flag is not None:
                slot = await self._poll_query_scan_slot(cache_key, flag.thresholds_fingerprint)
                if slot is not None:
                    response["query_scan"]["status"] = str(slot.status)
                    response["warnings"] = [
                        finding.model_dump(by_alias=True, exclude_none=True) for finding in slot.findings
                    ]
            return format_query_scan_warnings(response, self._team, compact=True).strip()
        except Exception:
            logger.warning(f"{TIMING_LOG_PREFIX} query scan block for a killed run failed", exc_info=True)
            return ""

    def _warning_prefix(self, response: dict) -> str:
        """The blocks that go above the results, however the results are rendered. A failure costs the
        warnings, never the results.
        """
        try:
            return (
                format_query_scan_warnings(response, self._team)
                + format_warehouse_sync_warnings(response)
                + format_access_control_warnings(response)
            )
        except Exception:
            logger.warning(f"{TIMING_LOG_PREFIX} warning prefix failed", exc_info=True)
            return ""

    async def _compress_results(
        self,
        query: AnyPydanticModelQuery | AnyAssistantGeneratedQuery,
        response: dict,
        debug_timing=False,
        truncate_results: bool = True,
    ) -> str:
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

        if not is_supported_query(query):
            raise NotImplementedError(f"Unsupported query type: {query_type}")

        # Outside the try, because the caller answers a formatter failure with raw JSON and the
        # warnings belong above that answer too.
        warning_prefix = self._warning_prefix(response)

        try:
            # Handle assistant-specific query types with direct formatting
            if isinstance(query, AssistantTrendsQuery | TrendsQuery):
                if is_boxplot_query(query):
                    formatter_name = "BoxPlotResultsFormatter"
                    result = BoxPlotResultsFormatter(get_boxplot_results(response)).format()
                else:
                    formatter_name = "TrendsResultsFormatter"
                    result = TrendsResultsFormatter(
                        query, response["results"], self._team, self._utc_now_datetime
                    ).format()
            elif isinstance(query, AssistantFunnelsQuery | FunnelsQuery):
                formatter_name = "FunnelResultsFormatter"
                formatter = FunnelResultsFormatter(query, response["results"], self._team, self._utc_now_datetime)
                # Contains a nested ClickHouse query in the date ranges
                result = await database_sync_to_async(formatter.format, thread_sensitive=False)()
            elif isinstance(query, AssistantLifecycleQuery | LifecycleQuery):
                formatter_name = "LifecycleResultsFormatter"
                result = LifecycleResultsFormatter(query, response["results"]).format()
            elif isinstance(query, AssistantPathsQuery | PathsQuery):
                formatter_name = "PathsResultsFormatter"
                result = PathsResultsFormatter(response["results"]).format()
            elif isinstance(query, AssistantStickinessQuery | StickinessQuery):
                formatter_name = "StickinessResultsFormatter"
                result = StickinessResultsFormatter(query, response["results"]).format()
            elif isinstance(query, AssistantRetentionQuery | RetentionQuery):
                formatter_name = "RetentionResultsFormatter"
                result = RetentionResultsFormatter(query, response["results"]).format()
            elif isinstance(query, DataVisualizationNode):
                formatter_name = "SQLResultsFormatter"
                max_cell_length = SQLResultsFormatter.MAX_CELL_LENGTH if truncate_results else None
                result = SQLResultsFormatter(
                    query.source, response["results"], response["columns"], max_cell_length=max_cell_length
                ).format()
            elif isinstance(query, AssistantHogQLQuery | HogQLQuery):
                formatter_name = "SQLResultsFormatter"
                max_cell_length = SQLResultsFormatter.MAX_CELL_LENGTH if truncate_results else None
                result = SQLResultsFormatter(
                    query, response["results"], response["columns"], max_cell_length=max_cell_length
                ).format()
            else:
                raise NotImplementedError(f"Unsupported query type: {query_type}")

            elapsed = time.time() - start_time
            if debug_timing:
                logger.warning(
                    f"{TIMING_LOG_PREFIX} {formatter_name}.format() completed in {elapsed:.3f}s for {query_type}"
                )

            return warning_prefix + result if warning_prefix else result
        except Exception:
            elapsed = time.time() - start_time
            if debug_timing:
                logger.exception(f"{TIMING_LOG_PREFIX} _compress_results failed after {elapsed:.3f}s for {query_type}")
            raise


def _is_boxplot_query(query: AnyPydanticModelQuery | AnyAssistantGeneratedQuery) -> bool:
    trends_filter = getattr(query, "trendsFilter", None)
    if trends_filter:
        display = getattr(trends_filter, "display", None)
        if display == ChartDisplayType.BOX_PLOT:
            return True
    return False


def get_example_prompt(query: AnyPydanticModelQuery | AnyAssistantGeneratedQuery) -> str:
    if isinstance(query, AssistantTrendsQuery | TrendsQuery):
        if _is_boxplot_query(query):
            return BOX_PLOT_EXAMPLE_PROMPT
        return TRENDS_EXAMPLE_PROMPT
    if isinstance(query, AssistantFunnelsQuery | FunnelsQuery):
        if (
            not query.funnelsFilter
            or not query.funnelsFilter.funnelVizType
            or query.funnelsFilter.funnelVizType == FunnelVizType.STEPS
        ):
            return FUNNEL_STEPS_EXAMPLE_PROMPT
        if query.funnelsFilter.funnelVizType == FunnelVizType.TIME_TO_CONVERT:
            return FUNNEL_TIME_TO_CONVERT_EXAMPLE_PROMPT
        return FUNNEL_TRENDS_EXAMPLE_PROMPT
    if isinstance(query, AssistantLifecycleQuery | LifecycleQuery):
        return LIFECYCLE_EXAMPLE_PROMPT
    if isinstance(query, AssistantPathsQuery | PathsQuery):
        return PATHS_EXAMPLE_PROMPT
    if isinstance(query, AssistantStickinessQuery | StickinessQuery):
        return STICKINESS_EXAMPLE_PROMPT
    if isinstance(query, AssistantRetentionQuery | RetentionQuery):
        return RETENTION_EXAMPLE_PROMPT
    if isinstance(query, AssistantHogQLQuery | HogQLQuery | DataVisualizationNode):
        return SQL_EXAMPLE_PROMPT
    raise NotImplementedError(f"Unsupported query type: {type(query)}")


async def execute_and_format_query(
    team: Team,
    query_model: AnyPydanticModelQuery | AnyAssistantGeneratedQuery,
    *,
    user: "User",
    execution_mode: Optional[ExecutionMode] = None,
    insight_id: Optional[int] = None,
    truncate_results: bool = True,
    include_prompt_framing: bool = True,
    event_source: EventSource = EventSource.POSTHOG_AI,
) -> str:
    """
    Executes a supported query and formats the results for the AI assistant:

    ```
    Format description...

    Query results...
    ```

    Args:
        team: The team to execute the query on.
        query: The query to execute.
        execution_mode: The execution mode to use.
        insight_id: The insight ID to use.
        include_prompt_framing: When False, return only the formatted results table without the
            example-format description and the surrounding `QUERY_RESULTS_PROMPT` system reminder.
            Used by the MCP `execute_sql` tool, which returns data straight to an external agent.
    Returns:
        The formatted query results.
    """
    query = validate_assistant_query(query_model.model_dump(mode="json"))
    utc_now_datetime = timezone.now().astimezone(UTC)
    query_runner = AssistantQueryExecutor(team, utc_now_datetime, user=user, event_source=event_source)

    results, used_fallback = await query_runner.arun_and_format_query(
        query, execution_mode, insight_id, truncate_results=truncate_results
    )
    if not include_prompt_framing:
        return results
    example_prompt = FALLBACK_EXAMPLE_PROMPT if used_fallback else get_example_prompt(query)

    insight_schema = ""
    if not isinstance(query, AssistantHogQLQuery | HogQLQuery):
        insight_schema = query.model_dump_json(exclude_none=True)

    # Check if SQL results contain truncated values
    has_truncated_values = isinstance(query, AssistantHogQLQuery | HogQLQuery | DataVisualizationNode) and (
        TRUNCATED_MARKER in results and not used_fallback
    )
    # Check if SQL results contain null values
    has_null_values = isinstance(query, AssistantHogQLQuery | HogQLQuery | DataVisualizationNode) and (
        NULL_MARKER in results and not used_fallback
    )

    query_result = format_prompt_string(
        QUERY_RESULTS_PROMPT,
        query_kind=query.kind,
        results=results,
        insight_schema=insight_schema,
        utc_datetime_display=utc_now_datetime.strftime("%Y-%m-%d %H:%M:%S"),
        project_datetime_display=utc_now_datetime.astimezone(team.timezone_info).strftime("%Y-%m-%d %H:%M:%S"),
        project_timezone=team.timezone_info.tzname(utc_now_datetime),
        has_truncated_values=has_truncated_values,
        has_null_values=has_null_values,
        sql_query=True if isinstance(query, AssistantHogQLQuery | HogQLQuery | DataVisualizationNode) else None,
    )

    return f"{example_prompt}\n\n{query_result}"
