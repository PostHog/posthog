import re
import time
import inspect
import warnings
from datetime import timedelta
from functools import wraps
from typing import Literal, Optional, TypedDict
from uuid import uuid4

from django.db.models import Max
from django.utils import timezone

import structlog
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from posthog.schema import AssistantMessage, AssistantToolCallMessage, VisualizationMessage

from posthog.exceptions_capture import capture_exception
from posthog.models import Insight

from ee.hogai.context import SUPPORTED_QUERY_MODEL_BY_KIND
from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.query_executor.query_executor import AssistantQueryExecutor, SupportedQueryTypes
from ee.hogai.graph.shared_prompts import HYPERLINK_USAGE_INSTRUCTIONS
from ee.hogai.utils.helpers import build_insight_url
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName
from ee.hogai.utils.types.composed import MaxNodeName

from .prompts import (
    EMPTY_DATABASE_ERROR_MESSAGE,
    ITERATIVE_SEARCH_SYSTEM_PROMPT,
    ITERATIVE_SEARCH_USER_PROMPT,
    NO_INSIGHTS_FOUND_MESSAGE,
    PAGINATION_INSTRUCTIONS_TEMPLATE,
    SEARCH_ERROR_INSTRUCTIONS,
    TOOL_BASED_EVALUATION_SYSTEM_PROMPT,
)

logger = structlog.get_logger(__name__)
# Silence Pydantic serializer warnings for creation of VisualizationMessage/Query execution
warnings.filterwarnings("ignore", category=UserWarning, message=".*Pydantic serializer.*")

TIMING_LOG_PREFIX = "[INSIGHT_SEARCH]"


def timing_logger(func_name: str | None = None):
    """Decorator to log execution time of functions.
    Investigating production bottleneck
    """

    def decorator(func):
        name = func_name or f"{func.__module__}.{func.__qualname__}"

        # Check async
        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.time()
                logger.warning(f"{TIMING_LOG_PREFIX} Starting {name}")
                try:
                    result = await func(*args, **kwargs)
                    elapsed = time.time() - start_time
                    logger.warning(f"{TIMING_LOG_PREFIX} {name} completed in {elapsed:.3f}s")
                    return result
                except Exception:
                    elapsed = time.time() - start_time
                    logger.exception(f"{TIMING_LOG_PREFIX} {name} failed after {elapsed:.3f}s")
                    raise

            return async_wrapper
        else:

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.time()
                logger.warning(f"{TIMING_LOG_PREFIX} Starting {name}")
                try:
                    result = func(*args, **kwargs)
                    elapsed = time.time() - start_time
                    logger.warning(f"{TIMING_LOG_PREFIX} {name} completed in {elapsed:.3f}s")
                    return result
                except Exception:
                    elapsed = time.time() - start_time
                    logger.exception(f"{TIMING_LOG_PREFIX} {name} failed after {elapsed:.3f}s")
                    raise

            return sync_wrapper

    return decorator


class InsightDict(TypedDict):
    """TypedDict for insight data returned from queryset.values()."""

    id: int
    name: Optional[str]
    description: Optional[str]
    query: Optional[dict]
    derived_name: Optional[str]
    short_id: str


class InsightSearchNode(AssistantNode):
    PAGE_SIZE = 500
    MAX_SEARCH_ITERATIONS = 6
    MAX_INSIGHTS_TO_RETURN = 3
    MAX_EVALUATION_ITERATIONS = 3
    INSIGHTS_CUTOFF_DAYS = 180
    MAX_SERIES_TO_PROCESS = 3

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.INSIGHTS_SEARCH

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_page = 0
        self._page_size = self.PAGE_SIZE
        self._max_iterations = self.MAX_SEARCH_ITERATIONS
        self._current_iteration = 0
        self._loaded_pages = {}
        self._total_insights_count = None
        self._max_insights_to_select = self.MAX_INSIGHTS_TO_RETURN
        self._max_insights_evaluation_iterations = self.MAX_EVALUATION_ITERATIONS
        self._evaluation_selections = {}
        self._rejection_reason = None
        self._cutoff_date_for_insights_in_days = self.INSIGHTS_CUTOFF_DAYS
        self._query_cache = {}
        self._insight_id_cache = {}

    def _dispatch_update_message(self, content: str) -> None:
        """Dispatch an update message to the assistant."""
        self.dispatcher.message(AssistantMessage(content=content))

    def _create_page_reader_tool(self):
        """Create tool for reading insights pages during agentic RAG loop."""

        @tool
        async def read_insights_page(page_number: int) -> str:
            """Read a page of insights data.

            Args:
                page_number: The page number to read (0-based)

            Returns:
                Formatted insights data for the requested page
            """
            page_insights = await self._load_insights_page(page_number)

            if not page_insights:
                return "No more insights available."

            formatted_insights = [self._format_insight_for_display(insight) for insight in page_insights]
            return f"Page {page_number + 1} insights:\n" + "\n".join(formatted_insights)

        return read_insights_page

    def _create_insight_evaluation_tools(self):
        """Create tools for insight evaluation."""

        @tool
        def select_insight(insight_id: int, explanation: str) -> str:
            """Select an insight as useful for the user's query."""
            insight = self._find_insight_by_id(insight_id)
            if not insight:
                return f"Insight {insight_id} not found"

            self._evaluation_selections[insight_id] = {"insight": insight, "explanation": explanation}

            name = insight["name"] or insight["derived_name"] or "Unnamed"
            insight_url = build_insight_url(self._team, insight["short_id"])
            return f"Selected insight {insight_id}: {name} (url: {insight_url})"

        @tool
        def reject_all_insights(reason: str) -> str:
            """Indicate that none of the insights are suitable."""
            self._evaluation_selections = {}
            self._rejection_reason = reason
            return "All insights rejected. Will create new insight."

        return [select_insight, reject_all_insights]

    @timing_logger("InsightSearchNode.arun")
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        self._dispatch_update_message("Searching for insights")
        search_query = state.search_insights_query
        try:
            self._current_iteration = 0

            total_count = await self._get_total_insights_count()
            if total_count == 0:
                return self._handle_empty_database(state)

            selected_insights = await self._search_insights_iteratively(search_query or "")
            logger.warning(
                f"{TIMING_LOG_PREFIX} search_insights_iteratively returned {len(selected_insights)} insights: {selected_insights}"
            )

            if selected_insights:
                self._dispatch_update_message(f"Evaluating {len(selected_insights)} insights to find the best match")
            else:
                self._dispatch_update_message("No existing insights found, creating a new one")

            evaluation_result = await self._evaluate_insights_with_tools(
                selected_insights, search_query or "", max_selections=1
            )

            return self._handle_evaluation_result(evaluation_result, state)

        except Exception as e:
            return self._handle_search_error(e, state)

    @timing_logger("InsightSearchNode._get_insights_queryset")
    def _get_insights_queryset(self):
        """Get Insight objects with latest view time annotated and cutoff date."""
        cutoff_date = timezone.now() - timedelta(days=self._cutoff_date_for_insights_in_days)
        return (
            Insight.objects.filter(team=self._team, deleted=False)
            # Annotate with latest view time from InsightViewed
            .annotate(latest_view_time=Max("insightviewed__last_viewed_at"))
            # Only include insights viewed within the last 6 months
            .filter(latest_view_time__gte=cutoff_date)
            .values("id", "name", "description", "query", "derived_name", "short_id")
            .order_by("-latest_view_time")
        )

    @timing_logger("InsightSearchNode._get_total_insights_count")
    async def _get_total_insights_count(self) -> int:
        if self._total_insights_count is None:
            self._total_insights_count = await self._get_insights_queryset().acount()
        return self._total_insights_count

    def _handle_empty_database(self, state: AssistantState) -> PartialAssistantState:
        """Handle the case when no insights exist in the database. (Rare edge-case but still possible)"""
        return self._create_error_response(EMPTY_DATABASE_ERROR_MESSAGE, state.root_tool_call_id)

    def _handle_evaluation_result(self, evaluation_result: dict, state: AssistantState) -> PartialAssistantState:
        """Process the evaluation result and return appropriate response."""
        if evaluation_result["should_use_existing"]:
            return self._create_existing_insights_response(evaluation_result, state)
        else:
            return self._create_new_insight_response(state.search_insights_query, state)

    @timing_logger("InsightSearchNode._create_existing_insights_response")
    def _create_existing_insights_response(
        self, evaluation_result: dict, state: AssistantState
    ) -> PartialAssistantState:
        """Create response for when existing insights are found."""
        formatted_content = f"**Evaluation Result**: {evaluation_result['explanation']}"
        formatted_content += HYPERLINK_USAGE_INSTRUCTIONS

        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(
                    content=formatted_content,
                    tool_call_id=state.root_tool_call_id or "unknown",
                    id=str(uuid4()),
                ),
                *evaluation_result["visualization_messages"],
            ],
            selected_insight_ids=evaluation_result["selected_insights"],
            search_insights_query=None,
            root_tool_call_id=None,
            root_tool_insight_plan=None,
        )

    def _create_new_insight_response(self, search_query: str | None, state: AssistantState) -> PartialAssistantState:
        """Create response for when no suitable insights are found."""
        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(
                    content=NO_INSIGHTS_FOUND_MESSAGE,
                    tool_call_id=state.root_tool_call_id or "unknown",
                    id=str(uuid4()),
                )
            ],
            root_tool_insight_plan=search_query,
            search_insights_query=None,
            selected_insight_ids=None,
        )

    @timing_logger("InsightSearchNode._handle_search_error")
    def _handle_search_error(self, e: Exception, state: AssistantState) -> PartialAssistantState:
        """Handle exceptions during search process."""
        capture_exception(e)
        logger.error(f"{TIMING_LOG_PREFIX} Error in InsightSearchNode: {e}", exc_info=True)
        return self._create_error_response(
            SEARCH_ERROR_INSTRUCTIONS,
            state.root_tool_call_id,
        )

    def _format_insight_for_display(self, insight: InsightDict) -> str:
        """Format a single insight for display."""
        name = insight["name"] or insight["derived_name"] or "Unnamed"
        description = insight["description"] or ""
        base = f"ID: {insight['id']} | {name}"
        return f"{base} - {description}" if description else base

    @timing_logger("InsightSearchNode._load_insights_page")
    async def _load_insights_page(self, page_number: int) -> list[InsightDict]:
        """Load a specific page of insights from database."""
        logger.warning(f"{TIMING_LOG_PREFIX} _load_insights_page called with page_number={page_number}")

        if page_number in self._loaded_pages:
            logger.info(
                f"{TIMING_LOG_PREFIX} Page {page_number} found in cache with {len(self._loaded_pages[page_number])} insights"
            )
            return self._loaded_pages[page_number]

        start_idx = page_number * self._page_size
        end_idx = start_idx + self._page_size

        insights_qs = self._get_insights_queryset()[start_idx:end_idx]
        logger.warning(
            f"{TIMING_LOG_PREFIX} Executing async query for page {page_number} (range: {start_idx}-{end_idx})"
        )

        db_start = time.time()
        page_insights = []
        insight_count = 0
        try:
            logger.warning(f"{TIMING_LOG_PREFIX} Starting async iteration for page {page_number}")

            last_progress_time = time.time()

            async for i in insights_qs:
                insight_count += 1
                page_insights.append(i)
                current_time = time.time()

                # Log progress every 100 insights or every 10 seconds in order to understand why we are getting stuck
                if insight_count % 100 == 0 or (current_time - last_progress_time) > 10:
                    elapsed_so_far = current_time - db_start
                    logger.warning(
                        f"{TIMING_LOG_PREFIX} Progress: loaded {insight_count} insights for page {page_number} in {elapsed_so_far:.2f}s"
                    )
                    last_progress_time = current_time

                # Certain insights may take too long
                # Certain insights may take too long - check against db_start instead of last_progress_time
                if (current_time - db_start) > 5 and insight_count == 1:
                    logger.warning(
                        f"{TIMING_LOG_PREFIX} Slow insight processing detected for page {page_number}, insight #{insight_count}"
                    )

            logger.warning(
                f"{TIMING_LOG_PREFIX} Async iteration completed for page {page_number}, total insights: {insight_count}"
            )

        except Exception as e:
            elapsed_on_error = time.time() - db_start
            logger.error(
                f"{TIMING_LOG_PREFIX} Exception during async iteration for page {page_number} after {elapsed_on_error:.2f}s, loaded {insight_count} insights: {e}",
                exc_info=True,
            )
            raise

        db_elapsed = time.time() - db_start

        logger.warning(
            f"{TIMING_LOG_PREFIX} Database query completed in {db_elapsed:.2f}s, loaded {len(page_insights)} insights for page {page_number}"
        )
        logger.warning(f"{TIMING_LOG_PREFIX} DB QUERY: took {db_elapsed:.2f}s to load page {page_number}")

        self._loaded_pages[page_number] = page_insights

        for insight in page_insights:
            self._insight_id_cache[insight["id"]] = insight

        return page_insights

    @timing_logger("InsightSearchNode._search_insights_iteratively")
    async def _search_insights_iteratively(self, search_query: str) -> list[int]:
        """Execute iterative insight search with LLM and tool calling."""
        messages = await self._build_search_messages(search_query)
        llm_with_tools = await self._prepare_llm_with_tools()

        selected_insights = await self._perform_iterative_search(messages, llm_with_tools)

        if not selected_insights:
            return []

        return selected_insights[: self._max_insights_to_select]

    async def _build_search_messages(self, search_query: str) -> list[BaseMessage]:
        """Build the initial messages for the search."""
        first_page = await self._format_insights_page(0)
        pagination_instructions = await self._get_pagination_instructions()

        system_prompt = ITERATIVE_SEARCH_SYSTEM_PROMPT.format(
            first_page_insights=first_page, pagination_instructions=pagination_instructions
        )
        user_prompt = ITERATIVE_SEARCH_USER_PROMPT.format(query=search_query)

        return [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]

    async def _get_pagination_instructions(self) -> str:
        """Get pagination instructions based on available insights."""
        total_insights = await self._get_total_insights_count()
        total_pages = self._calculate_total_pages(total_insights)

        if total_pages > 1:
            return PAGINATION_INSTRUCTIONS_TEMPLATE.format(total_pages=total_pages)
        return "This is the only page of insights available."

    async def _prepare_llm_with_tools(self):
        """Prepare LLM with pagination tools if needed."""
        total_insights = await self._get_total_insights_count()
        total_pages = self._calculate_total_pages(total_insights)

        if total_pages > 1:
            read_tool = self._create_page_reader_tool()
            return self._model.bind_tools([read_tool])
        return self._model

    @timing_logger("InsightSearchNode._perform_iterative_search")
    async def _perform_iterative_search(self, messages: list[BaseMessage], llm_with_tools) -> list[int]:
        """Perform the iterative search with the LLM."""
        selected_insights = []

        for step in ["Searching through existing insights", "Analyzing available insights"]:
            self._dispatch_update_message(step)
        logger.warning(f"{TIMING_LOG_PREFIX} Starting iterative search, max_iterations={self._max_iterations}")

        while self._current_iteration < self._max_iterations:
            self._current_iteration += 1
            logger.warning(f"{TIMING_LOG_PREFIX} Iteration {self._current_iteration}/{self._max_iterations} starting")

            try:
                response = await llm_with_tools.ainvoke(messages)

                if hasattr(response, "tool_calls") and response.tool_calls:
                    # Required for tool message protocol
                    messages.append(response)

                    for tool_call in response.tool_calls:
                        if tool_call.get("name") == "read_insights_page":
                            page_num = tool_call.get("args", {}).get("page_number", 0)
                            logger.warning(f"{TIMING_LOG_PREFIX} Reading insights page {page_num}")

                            logger.warning(
                                f"{TIMING_LOG_PREFIX} STALL POINT(?): Streamed 'Finding the most relevant insights' - about to fetch page content"
                            )
                            self._dispatch_update_message("Finding the most relevant insights")

                            logger.warning(f"{TIMING_LOG_PREFIX} Fetching page content for page {page_num}")
                            tool_response = await self._get_page_content_for_tool(page_num)
                            logger.warning(
                                f"{TIMING_LOG_PREFIX} Page content fetched successfully, length={len(tool_response)}"
                            )

                            messages.append(
                                ToolMessage(content=tool_response, tool_call_id=tool_call.get("id", "unknown"))
                            )

                    logger.warning(f"{TIMING_LOG_PREFIX} Continuing to next iteration after tool calls")
                    continue

                # No tool calls, extract insight IDs from the response. Done with the search
                content = response.content if isinstance(response.content, str) else str(response.content)
                selected_insights = self._parse_insight_ids(content)
                if selected_insights:
                    self._dispatch_update_message(f"Found {len(selected_insights)} relevant insights")
                else:
                    self._dispatch_update_message("No matching insights found")
                break

            except Exception as e:
                capture_exception(e)
                error_message = f"Error during search"
                self._dispatch_update_message(error_message)
                break

        return selected_insights

    async def _get_page_content_for_tool(self, page_number: int) -> str:
        """Get page content for tool response."""
        if page_number == 0:
            return "Page 0 data is already provided in the initial context above."
        else:
            page_content = await self._format_insights_page(page_number)
            return f"Page {page_number + 1} results:\n{page_content}"

    def _calculate_total_pages(self, total_insights: int) -> int:
        """Calculate total number of pages for insights."""
        return (total_insights + self._page_size - 1) // self._page_size

    async def _format_insights_page(self, page_number: int) -> str:
        """Format a page of insights for display."""
        page_insights = await self._load_insights_page(page_number)

        if not page_insights:
            return "No insights available on this page."

        formatted_insights = [self._format_insight_for_display(insight) for insight in page_insights]
        return "\n".join(formatted_insights)

    @timing_logger("InsightSearchNode._get_all_loaded_insight_ids")
    def _get_all_loaded_insight_ids(self) -> set[int]:
        """Get all insight IDs from loaded pages."""
        all_ids = set()
        for page_insights in self._loaded_pages.values():
            for insight in page_insights:
                all_ids.add(insight["id"])
        return all_ids

    @timing_logger("InsightSearchNode._find_insight_by_id")
    def _find_insight_by_id(self, insight_id: int) -> InsightDict | None:
        """Find an insight by ID across all loaded pages (with cache)."""
        return self._insight_id_cache.get(insight_id)

    @timing_logger("InsightSearchNode._process_insight_query")
    async def _process_insight_query(self, insight: InsightDict) -> tuple[SupportedQueryTypes | None, str | None]:
        """
        Process an insight's query and cache object and formatted results for reference
        """
        insight_id = insight["id"]

        cached_result = self._get_cached_query(insight_id)
        if cached_result is not None:
            return cached_result

        if not insight["query"]:
            return self._cache_and_return(insight_id, None, None)

        query_obj, formatted_results = await self._extract_and_execute_query(insight)

        return self._cache_and_return(insight_id, query_obj, formatted_results)

    def _get_cached_query(self, insight_id: int) -> tuple[SupportedQueryTypes | None, str | None] | None:
        """Get cached query result if available."""
        if insight_id in self._query_cache:
            return self._query_cache[insight_id]
        return None

    def _cache_and_return(
        self,
        insight_id: int,
        query_obj: SupportedQueryTypes | None,
        formatted_results: str | None,
    ) -> tuple[SupportedQueryTypes | None, str | None]:
        """Cache and return query result."""
        result = (query_obj, formatted_results)
        self._query_cache[insight_id] = result
        return result

    @timing_logger("InsightSearchNode._extract_and_execute_query")
    async def _extract_and_execute_query(self, insight: InsightDict) -> tuple[SupportedQueryTypes | None, str | None]:
        """Extract query object and execute it."""
        try:
            query_dict = insight["query"]
            if query_dict is None:
                return None, "Query is missing"
            query_source = query_dict.get("source", {})
            insight_type = query_source.get("kind", "Unknown")

            query_obj = self._validate_and_create_query_object(insight_type, query_source)
            if query_obj is None:
                return None, "Query type not supported for execution"

            formatted_results = await self._execute_and_format_query(query_obj, insight["id"])
            return query_obj, formatted_results

        except Exception as e:
            capture_exception(e)
            return None, "Query processing failed"

    @timing_logger("InsightSearchNode._validate_and_create_query_object")
    def _validate_and_create_query_object(self, insight_type: str, query_source: dict) -> SupportedQueryTypes | None:
        """Validate query type and create query object."""
        if insight_type not in SUPPORTED_QUERY_MODEL_BY_KIND:
            return None

        AssistantQueryModel = SUPPORTED_QUERY_MODEL_BY_KIND[insight_type]
        return AssistantQueryModel.model_validate(query_source, strict=False)

    @timing_logger("InsightSearchNode._execute_and_format_query")
    async def _execute_and_format_query(self, query_obj: SupportedQueryTypes, insight_id: int) -> str:
        """Execute query and format results with timing instrumentation."""
        try:
            query_executor = AssistantQueryExecutor(team=self._team, utc_now_datetime=self._utc_now_datetime)
            results, _ = await query_executor.arun_and_format_query(query_obj, debug_timing=True)
            return results
        except Exception as e:
            capture_exception(e)
            return "Query execution failed"

    @timing_logger("InsightSearchNode._parse_insight_ids")
    def _parse_insight_ids(self, response_content: str) -> list[int]:
        """Parse insight IDs from LLM response, removing duplicates and preserving order."""
        numbers = re.findall(r"\b\d+\b", response_content)

        # Convert to integers and validate against available insights
        available_ids = self._get_all_loaded_insight_ids()
        valid_ids = []
        seen_ids = set()

        for num_str in numbers:
            try:
                insight_id = int(num_str)
                if insight_id in available_ids and insight_id not in seen_ids:
                    valid_ids.append(insight_id)
                    seen_ids.add(insight_id)
                    # Stop if we've found enough unique insights
                    if len(valid_ids) >= self._max_insights_to_select:
                        break
            except ValueError:
                continue

        return valid_ids

    @timing_logger("InsightSearchNode._create_enhanced_insight_summary")
    async def _create_enhanced_insight_summary(self, insight: InsightDict) -> str:
        """Create enhanced summary with metadata and basic execution info."""
        insight_id = insight["id"]
        name = insight["name"] or insight["derived_name"] or "Unnamed"
        description = insight["description"] or ""

        insight_type = "Unknown"
        query_info = None

        _, query_result = await self._process_insight_query(insight)

        if insight["query"]:
            try:
                query_dict = insight["query"]
                query_source = query_dict.get("source", {})
                insight_type = query_source.get("kind", "Unknown")
                query_info = self._extract_query_metadata(query_source)
            except Exception as e:
                capture_exception(e)

        insight_url = build_insight_url(self._team, insight["short_id"])
        hyperlink_format = f"[{name}]({insight_url})"

        summary_parts = [
            f"ID: {insight_id} | {name} | {hyperlink_format}",
            f"Type: {insight_type}",
            f"Query result: {query_result}",
        ]

        if description:
            summary_parts.append(f"Description: {description}")

        if query_info:
            summary_parts.append(f"Query: {query_info}")

        return " | ".join(summary_parts)

    @timing_logger("InsightSearchNode._extract_query_metadata")
    def _extract_query_metadata(self, query_source: dict) -> str | None:
        """Extract basic query information from Insight object without execution."""
        try:
            if not query_source:
                return None

            # Extract basic info from query
            info_parts = []

            # Get events/series info - only process first 3 for efficiency
            series = query_source.get("series", [])
            if series:
                events = []
                for series_item in series[: self.MAX_SERIES_TO_PROCESS]:
                    if isinstance(series_item, dict):
                        event_name = series_item.get("event", series_item.get("name", "Unknown"))
                        if event_name:
                            events.append(str(event_name))
                if events:
                    info_parts.append(f"Events: {', '.join(events)}")

            # Get date range info
            date_range = query_source.get("dateRange", {})
            if date_range:
                date_from = date_range.get("date_from", "")
                if date_from:
                    info_parts.append(f"Period: {date_from}")

            return " | ".join(info_parts) if info_parts else None

        except Exception as e:
            capture_exception(e)
            return None

    @timing_logger("InsightSearchNode._create_visualization_message_for_insight")
    async def _create_visualization_message_for_insight(self, insight: InsightDict) -> VisualizationMessage | None:
        """Create a VisualizationMessage to render the insight UI."""
        try:
            for step in ["Executing insight query...", "Processing query parameters", "Running data analysis"]:
                self._dispatch_update_message(step)

            query_obj, _ = await self._process_insight_query(insight)

            if not query_obj:
                return None

            insight_name = insight["name"] or insight["derived_name"] or "Unnamed Insight"

            visualization_message = VisualizationMessage(
                query=f"Existing insight: {insight_name}",
                plan=f"Showing existing insight: {insight_name}",
                answer=query_obj,
                id=str(uuid4()),
                short_id=insight["short_id"],
            )

            return visualization_message

        except Exception as e:
            capture_exception(e)
            return None

    def _create_error_response(self, content: str, tool_call_id: str | None) -> PartialAssistantState:
        """Create error response for the assistant."""
        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(
                    content=content,
                    tool_call_id=tool_call_id or "unknown",
                    id=str(uuid4()),
                ),
            ],
            search_insights_query=None,
            root_tool_call_id=None,
        )

    @timing_logger("InsightSearchNode._evaluate_insights_with_tools")
    async def _evaluate_insights_with_tools(
        self, selected_insights: list[int], user_query: str, max_selections: int = 1
    ) -> dict:
        """Evaluate insights using tool calls for fine-grained selection.

        Args:
            selected_insights: List of insight IDs to evaluate
            user_query: The user's search query
            max_selections: Maximum number of insights to select (default: 1, best possible match)
        """
        self._reset_evaluation_state()

        insights_summary, final_selected_insights = await self._prepare_insights_for_evaluation(selected_insights)

        if not final_selected_insights:
            return self._no_insights_found_result()

        await self._run_evaluation_loop(user_query, insights_summary, max_selections)

        if self._evaluation_selections:
            return await self._create_successful_evaluation_result()
        else:
            return await self._create_rejection_result()

    def _reset_evaluation_state(self) -> None:
        """Reset evaluation state for new evaluation."""
        self._evaluation_selections = {}
        self._rejection_reason = None

    async def _prepare_insights_for_evaluation(self, selected_insights: list[int]) -> tuple[list[str], list[int]]:
        """Prepare insights for evaluation."""
        insights_summary = []
        final_selected_insights = []

        for insight_id in selected_insights:
            insight = self._find_insight_by_id(insight_id)
            if insight:
                enhanced_summary = await self._create_enhanced_insight_summary(insight)
                insights_summary.append(enhanced_summary)
                final_selected_insights.append(insight_id)

        return insights_summary, final_selected_insights

    def _no_insights_found_result(self) -> dict:
        """Return result when no insights are found."""
        return {
            "should_use_existing": False,
            "selected_insights": [],
            "explanation": "No insights found matching the user's query.",
            "visualization_messages": [],
        }

    @timing_logger("InsightSearchNode._run_evaluation_loop")
    async def _run_evaluation_loop(self, user_query: str, insights_summary: list[str], max_selections: int) -> None:
        """Run the evaluation loop with LLM."""
        for step in ["Analyzing insights to match your request", "Comparing insights for best fit"]:
            self._dispatch_update_message(step)

        tools = self._create_insight_evaluation_tools()
        llm_with_tools = self._model.bind_tools(tools)

        selection_instruction = self._build_selection_instruction(max_selections)
        messages = self._build_evaluation_messages(user_query, insights_summary, selection_instruction)

        for iteration in range(self._max_insights_evaluation_iterations):
            response = await llm_with_tools.ainvoke(messages)

            if getattr(response, "tool_calls", None):
                # Only stream on first iteration to avoid noise
                if iteration == 0:
                    self._dispatch_update_message("Making evaluation decisions")
                self._process_evaluation_tool_calls(response, messages, tools)
            else:
                break

    def _build_selection_instruction(self, max_selections: int) -> str:
        """Build instruction for insight selection."""
        insight_word = "insight" if max_selections == 1 else "insights"
        verb = "matches" if max_selections == 1 else "match"
        return f"Select ONLY the {max_selections} BEST {insight_word} that {verb} the user's query."

    def _build_evaluation_messages(
        self, user_query: str, insights_summary: list[str], selection_instruction: str
    ) -> list[BaseMessage]:
        """Build messages for evaluation."""
        system_prompt = TOOL_BASED_EVALUATION_SYSTEM_PROMPT.format(
            user_query=user_query,
            insights_summary=chr(10).join(insights_summary),
            selection_instruction=selection_instruction,
        )
        return [SystemMessage(content=system_prompt)]

    def _process_evaluation_tool_calls(self, response, messages: list[BaseMessage], tools: list) -> None:
        """Process tool calls during evaluation."""
        messages.append(response)

        for tool_call in response.tool_calls:
            if tool_call["name"] in ["select_insight", "reject_all_insights"]:
                tool_fn = next(t for t in tools if t.name == tool_call["name"])
                result = tool_fn.invoke(tool_call["args"])
                messages.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))

    @timing_logger("InsightSearchNode._create_successful_evaluation_result")
    async def _create_successful_evaluation_result(self) -> dict:
        """Create result for successful evaluation."""
        visualization_messages = []
        explanations = []

        num_insights = len(self._evaluation_selections)
        insight_word = "insight" if num_insights == 1 else "insights"

        self._dispatch_update_message(f"Perfect! Found {num_insights} suitable {insight_word}")

        for _, selection in self._evaluation_selections.items():
            insight = selection["insight"]
            visualization_message = await self._create_visualization_message_for_insight(insight)
            if visualization_message:
                visualization_messages.append(visualization_message)

            insight_name = insight["name"] or insight["derived_name"] or "Unnamed"
            insight_url = build_insight_url(self._team, insight["short_id"])
            insight_hyperlink = f"[{insight_name}]({insight_url})"
            explanations.append(f"- {insight_hyperlink}: {selection['explanation']}")

        num_insights = len(self._evaluation_selections)

        # If no insights were actually selected, this shouldn't be a successful result
        if num_insights == 0:
            return await self._create_rejection_result()

        insight_word = "insight" if num_insights == 1 else "insights"

        return {
            "should_use_existing": True,
            "selected_insights": list(self._evaluation_selections.keys()),
            "explanation": f"Found {num_insights} relevant {insight_word}:\n" + "\n".join(explanations),
            "visualization_messages": visualization_messages,
        }

    async def _create_rejection_result(self) -> dict:
        """Create result for when all insights are rejected."""
        self._dispatch_update_message("Will create a custom insight tailored to your request")

        return {
            "should_use_existing": False,
            "selected_insights": [],
            "explanation": self._rejection_reason or "No suitable insights found.",
            "visualization_messages": [],
        }

    def router(self, state: AssistantState) -> Literal["root"]:
        return "root"

    @property
    def _model(self):
        return ChatOpenAI(
            model="gpt-4.1-mini",
            temperature=0.7,
            max_completion_tokens=1000,
            streaming=False,
            stream_usage=False,
            max_retries=3,
            disable_streaming=True,
        )
