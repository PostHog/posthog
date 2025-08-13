import re
from typing import Literal
from uuid import uuid4
import warnings

from langchain_core.runnables import RunnableConfig
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from langchain_openai import ChatOpenAI

from ee.hogai.graph.query_executor.query_executor import AssistantQueryExecutor
from ee.hogai.graph.root.nodes import MAX_SUPPORTED_QUERY_KIND_TO_MODEL
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import (
    AssistantToolCallMessage,
    VisualizationMessage,
)
from ee.hogai.graph.base import AssistantNode
from .prompts import (
    ITERATIVE_SEARCH_SYSTEM_PROMPT,
    ITERATIVE_SEARCH_USER_PROMPT,
    PAGINATION_INSTRUCTIONS_TEMPLATE,
    HYPERLINK_USAGE_INSTRUCTIONS,
    TOOL_BASED_EVALUATION_SYSTEM_PROMPT,
    NO_INSIGHTS_FOUND_MESSAGE,
    SEARCH_ERROR_INSTRUCTIONS,
    EMPTY_DATABASE_ERROR_MESSAGE,
)

from posthog.models import Insight
from django.db.models import Max
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)
# Silence Pydantic serializer warnings for creation of VisualizationMessage/Query execution
warnings.filterwarnings("ignore", category=UserWarning, message=".*Pydantic serializer.*")


class InsightSearchNode(AssistantNode):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_page = 0
        self._page_size = 50
        self._max_iterations = 6
        self._current_iteration = 0
        self._loaded_pages = {}
        self._total_insights_count = None
        self._max_insights = 3
        self._max_insights_evaluation_iterations = 3
        self._evaluation_selections = {}
        self._rejection_reason = None
        self._cutoff_date_for_insights_in_days = 180
        self._query_cache = {}

    def _create_read_insights_tool(self):
        """Create tool for reading insights pages during agentic RAG loop."""

        @tool
        def read_insights_page(page_number: int) -> str:
            """Read a page of insights data.

            Args:
                page_number: The page number to read (0-based)

            Returns:
                Formatted insights data for the requested page
            """
            page_insights = self._load_insights_page(page_number)

            if not page_insights:
                return "No more insights available."

            formatted_insights = []
            for insight in page_insights:
                name = insight.name or insight.derived_name or "Unnamed"
                description = insight.description or ""
                insight_id = insight.id

                if description:
                    formatted_insights.append(f"ID: {insight_id} | {name} - {description}")
                else:
                    formatted_insights.append(f"ID: {insight_id} | {name}")

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

            name = insight.name or insight.derived_name or "Unnamed"
            insight_url = f"/project/{self._team.id}/insights/{insight.short_id}"
            return f"Selected insight {insight_id}: {name} (url: {insight_url})"

        @tool
        def reject_all_insights(reason: str) -> str:
            """Indicate that none of the insights are suitable."""
            self._evaluation_selections = {}
            self._rejection_reason = reason
            return "All insights rejected. Will create new insight."

        return [select_insight, reject_all_insights]

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        search_query = state.search_insights_query

        try:
            self._current_iteration = 0

            # Check if we have any insights at all
            if self._get_total_insights_count() == 0:
                return self._create_error_response(EMPTY_DATABASE_ERROR_MESSAGE, state.root_tool_call_id)

            selected_insights = self._search_insights_iteratively(search_query or "")

            evaluation_result = self._evaluate_insights_with_tools(
                selected_insights, search_query or "", max_selections=1
            )

            if evaluation_result["should_use_existing"]:
                # Create visualization messages for the insights to show actual charts
                messages_to_return = []

                formatted_content = f"**Evaluation Result**: {evaluation_result['explanation']}"

                formatted_content += HYPERLINK_USAGE_INSTRUCTIONS

                messages_to_return.append(
                    AssistantToolCallMessage(
                        content=formatted_content,
                        tool_call_id=state.root_tool_call_id or "unknown",
                        id=str(uuid4()),
                    )
                )

                # Add visualization messages returned from evaluation
                messages_to_return.extend(evaluation_result["visualization_messages"])

                return PartialAssistantState(
                    messages=messages_to_return,
                    search_insights_query=None,
                    root_tool_call_id=None,
                    root_tool_insight_plan=None,
                )
            else:
                # No suitable insights found, triggering creation of a new insight
                no_insights_message = AssistantToolCallMessage(
                    content=NO_INSIGHTS_FOUND_MESSAGE,
                    tool_call_id=state.root_tool_call_id or "unknown",
                    id=str(uuid4()),
                )
                return PartialAssistantState(
                    messages=[no_insights_message],
                    root_tool_insight_plan=search_query,
                    search_insights_query=None,
                )

        except Exception as e:
            logger.error(f"Error in InsightSearchNode: {e}", exc_info=True)
            return self._create_error_response(
                SEARCH_ERROR_INSTRUCTIONS,
                state.root_tool_call_id,
            )

    def _get_insights_queryset(self):
        """Get Insight objects with latest view time annotated and cutoff date."""
        cutoff_date = timezone.now() - timedelta(days=self._cutoff_date_for_insights_in_days)
        return (
            Insight.objects.filter(team=self._team, deleted=False)
            # Annotate with latest view time from InsightViewed
            .annotate(latest_view_time=Max("insightviewed__last_viewed_at"))
            # Only include insights viewed within the last 6 months
            .filter(latest_view_time__gte=cutoff_date)
            .select_related("team", "created_by")
            .order_by("-latest_view_time")
        )

    def _get_total_insights_count(self) -> int:
        if self._total_insights_count is None:
            self._total_insights_count = self._get_insights_queryset().count()
        return self._total_insights_count

    def _load_insights_page(self, page_number: int) -> list[Insight]:
        """Load a specific page of insights from database."""
        if page_number in self._loaded_pages:
            return self._loaded_pages[page_number]

        start_idx = page_number * self._page_size
        end_idx = start_idx + self._page_size

        insights_qs = self._get_insights_queryset()[start_idx:end_idx]
        page_insights = list(insights_qs)

        self._loaded_pages[page_number] = page_insights
        return page_insights

    def _search_insights_iteratively(self, search_query: str) -> list[int]:
        """Execute iterative insight search with LLM and tool calling."""
        first_page = self._format_insights_page(0)

        total_insights = self._get_total_insights_count()
        total_pages = (total_insights + self._page_size - 1) // self._page_size
        has_pagination = total_pages > 1

        pagination_instructions = (
            PAGINATION_INSTRUCTIONS_TEMPLATE.format(total_pages=total_pages)
            if has_pagination
            else "This is the only page of insights available."
        )

        system_prompt = ITERATIVE_SEARCH_SYSTEM_PROMPT.format(
            first_page_insights=first_page, pagination_instructions=pagination_instructions
        )

        user_prompt = ITERATIVE_SEARCH_USER_PROMPT.format(query=search_query)

        messages: list[BaseMessage] = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]

        if has_pagination:
            read_tool = self._create_read_insights_tool()
            llm_with_tools = self._model.bind_tools([read_tool])
        else:
            llm_with_tools = self._model

        selected_insights = []

        while self._current_iteration < self._max_iterations:
            self._current_iteration += 1

            try:
                response = llm_with_tools.invoke(messages)

                if hasattr(response, "tool_calls") and getattr(response, "tool_calls", None):
                    messages.append(response)

                    for tool_call in response.tool_calls:
                        if tool_call["name"] == "read_insights_page":
                            page_number = tool_call["args"]["page_number"]

                            if page_number == 0:
                                tool_content = "Page 0 data is already provided in the initial context above."
                            else:
                                page_content = self._format_insights_page(page_number)
                                tool_content = f"Page {page_number + 1} results:\n{page_content}"

                            messages.append(ToolMessage(content=tool_content, tool_call_id=tool_call["id"]))
                else:
                    # Parse final response for insight IDs
                    content = response.content if isinstance(response.content, str) else str(response.content)
                    selected_insights = self._parse_insight_ids(content)
                    break

            except Exception:
                break

        if not selected_insights:
            return []

        return selected_insights[: self._max_insights]

    def _format_insights_page(self, page_number: int) -> str:
        """Format a page of insights for display."""
        page_insights = self._load_insights_page(page_number)

        if not page_insights:
            return "No insights available on this page."

        formatted_insights = []
        for insight in page_insights:
            name = insight.name or insight.derived_name or "Unnamed"
            description = insight.description or ""
            insight_id = insight.id

            if description:
                formatted_insights.append(f"ID: {insight_id} | {name} - {description}")
            else:
                formatted_insights.append(f"ID: {insight_id} | {name}")

        return "\n".join(formatted_insights)

    def _get_all_loaded_insight_ids(self) -> set[int]:
        """Get all insight IDs from loaded pages."""
        all_ids = set()
        for page_insights in self._loaded_pages.values():
            for insight in page_insights:
                all_ids.add(insight.id)
        return all_ids

    def _find_insight_by_id(self, insight_id: int) -> Insight | None:
        """Find an insight by ID across all loaded pages."""
        for page_insights in self._loaded_pages.values():
            for insight in page_insights:
                if insight.id == insight_id:
                    return insight
        return None

    def _process_insight_query(self, insight: Insight) -> tuple[object | None, str | None]:
        """
        Process an insight's query and cache object and formatted results for reference
        """
        insight_id = insight.id

        # Check cache
        if insight_id in self._query_cache:
            return self._query_cache[insight_id]

        query_obj = None
        formatted_results = None

        if not insight.query:
            self._query_cache[insight_id] = (None, None)
            return None, None

        try:
            query_dict = insight.query
            query_source = query_dict.get("source", {})
            insight_type = query_source.get("kind", "Unknown")

            if insight_type not in MAX_SUPPORTED_QUERY_KIND_TO_MODEL:
                result = (None, "Query type not supported for execution")
                self._query_cache[insight_id] = result
                return result

            AssistantQueryModel = MAX_SUPPORTED_QUERY_KIND_TO_MODEL[insight_type]
            query_obj = AssistantQueryModel.model_validate(query_source, strict=False)

            try:
                query_executor = AssistantQueryExecutor(team=self._team, utc_now_datetime=self._utc_now_datetime)
                query_result_dict = query_executor._execute_query(query_obj)
                formatted_results = query_executor._compress_results(query_obj, query_result_dict)
            except Exception as e:
                logger.warning(f"Failed to execute query for insight {insight_id}: {e}")
                formatted_results = "Query execution failed"

        except Exception as e:
            logger.warning(f"Failed to process query for insight {insight_id}: {e}")
            formatted_results = "Query processing failed"

        result = (query_obj, formatted_results)
        self._query_cache[insight_id] = result
        return result

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
                    if len(valid_ids) >= self._max_insights:
                        break
            except ValueError:
                continue

        return valid_ids

    def _create_enhanced_insight_summary(self, insight: Insight) -> str:
        """Create enhanced summary with metadata and basic execution info."""
        insight_id = insight.id
        name = insight.name or insight.derived_name or "Unnamed"
        description = insight.description or ""

        insight_type = "Unknown"
        query_info = None

        _, query_result = self._process_insight_query(insight)

        if insight.query:
            try:
                query_dict = insight.query
                query_source = query_dict.get("source", {})
                insight_type = query_source.get("kind", "Unknown")
                query_info = self._get_basic_query_info_from_insight(query_source)
            except Exception:
                pass

        insight_url = f"/project/{self._team.id}/insights/{insight.short_id}"
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

    def _get_basic_query_info_from_insight(self, query_source: dict) -> str | None:
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
                for s in series[:3]:
                    if isinstance(s, dict):
                        event_name = s.get("event", s.get("name", "Unknown"))
                        events.append(event_name)
                if events:
                    info_parts.append(f"Events: {', '.join(events)}")

            # Get date range info
            date_range = query_source.get("dateRange", {})
            if date_range:
                date_from = date_range.get("date_from", "")
                if date_from:
                    info_parts.append(f"Period: {date_from}")

            return " | ".join(info_parts) if info_parts else None

        except Exception:
            return None

    def _create_visualization_message_for_insight(self, insight: Insight) -> VisualizationMessage | None:
        """Create a VisualizationMessage to render the insight UI."""
        try:
            query_obj, _ = self._process_insight_query(insight)

            if not query_obj:
                return None

            insight_name = insight.name or insight.derived_name or "Unnamed Insight"

            viz_message = VisualizationMessage.model_construct(
                query=f"Existing insight: {insight_name}",
                plan=f"Showing existing insight: {insight_name}",
                answer=query_obj,
                id=str(uuid4()),
            )

            return viz_message

        except Exception as e:
            logger.error(f"Error creating visualization message for insight {insight.id}: {e}", exc_info=True)
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

    def _evaluate_insights_with_tools(
        self, selected_insights: list[int], user_query: str, max_selections: int = 1
    ) -> dict:
        """Evaluate insights using tool calls for fine-grained selection.

        Args:
            selected_insights: List of insight IDs to evaluate
            user_query: The user's search query
            max_selections: Maximum number of insights to select (default: 1, best possible match)
        """
        self._evaluation_selections = {}
        self._rejection_reason = None

        tools = self._create_insight_evaluation_tools()
        llm_with_tools = self._model.bind_tools(tools)

        insights_summary = []
        final_selected_insights = []

        for insight_id in selected_insights:
            insight = self._find_insight_by_id(insight_id)
            if insight:
                enhanced_summary = self._create_enhanced_insight_summary(insight)
                insights_summary.append(enhanced_summary)
                final_selected_insights.append(insight_id)

        if not final_selected_insights:
            return {
                "should_use_existing": False,
                "selected_insights": [],
                "explanation": "No insights found matching the user's query.",
                "visualization_messages": [],
            }

        selection_instruction = f"Select ONLY the {max_selections} BEST insight{'s' if max_selections > 1 else ''} that match{'es' if max_selections == 1 else ''} the user's query."

        system_prompt = TOOL_BASED_EVALUATION_SYSTEM_PROMPT.format(
            user_query=user_query,
            insights_summary=chr(10).join(insights_summary),
            selection_instruction=selection_instruction,
        )

        messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]

        for _ in range(self._max_insights_evaluation_iterations):
            response = llm_with_tools.invoke(messages)

            if hasattr(response, "tool_calls") and response.tool_calls:
                messages.append(response)

                for tool_call in response.tool_calls:
                    if tool_call["name"] in ["select_insight", "reject_all_insights"]:
                        tool_fn = next(t for t in tools if t.name == tool_call["name"])
                        result = tool_fn.invoke(tool_call["args"])
                        messages.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))
            else:
                break

        if self._evaluation_selections:
            # Create visualization messages for selected insights
            visualization_messages = []
            explanations = []

            for _insight_id, selection in self._evaluation_selections.items():
                insight = selection["insight"]
                viz_message = self._create_visualization_message_for_insight(insight)
                if viz_message:
                    visualization_messages.append(viz_message)

                insight_name = insight.name or insight.derived_name or "Unnamed"
                insight_url = f"/project/{self._team.id}/insights/{insight.short_id}"
                insight_hyperlink = f"[{insight_name}]({insight_url})"
                explanations.append(f"- {insight_hyperlink}: {selection['explanation']}")

            return {
                "should_use_existing": True,
                "selected_insights": list(self._evaluation_selections.keys()),
                "explanation": f"Found {len(self._evaluation_selections)} relevant insight{'s' if len(self._evaluation_selections) != 1 else ''}:\n"
                + "\n".join(explanations),
                "visualization_messages": visualization_messages,
            }
        else:
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
            streaming=True,
            stream_usage=True,
            max_retries=3,
        )
