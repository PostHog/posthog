import json
import re
from typing import Literal
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from langchain_openai import ChatOpenAI


from ee.hogai.graph.query_executor.query_executor import AssistantQueryExecutor
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import (
    AssistantToolCallMessage,
    VisualizationMessage,
    AssistantTrendsQuery,
    AssistantFunnelsQuery,
    AssistantRetentionQuery,
    AssistantHogQLQuery,
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
from .utils import convert_filters_to_query, get_insight_type_from_filters

from posthog.models import Insight
from django.db.models import Max
from django.utils import timezone
from datetime import timedelta


class InsightSearchNode(AssistantNode):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_page = 0
        self._page_size = 300
        self._max_iterations = 6
        self._current_iteration = 0
        self._loaded_pages = {}
        self._total_insights_count = None
        self._max_insights = 3
        self._max_insights_evaluation_iterations = 3
        self._evaluation_selections = {}
        self._rejection_reason = None
        self._cutoff_date_for_insights_in_days = 180

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
            return f"Selected insight {insight_id}: {name}"

        @tool
        def get_insight_details(insight_id: int) -> str:
            """Get detailed information (with query execution)about an insight including its current results."""
            insight = self._find_insight_by_id(insight_id)
            if not insight:
                return f"Insight {insight_id} not found"

            insight_info = self._process_insight_for_evaluation(
                insight, AssistantQueryExecutor(self._team, self._utc_now_datetime)
            )

            insight_url = f"/project/{self._team.id}/insights/{insight.short_id}"
            hyperlink_format = f"[{insight_info['name']}]({insight_url})"

            return f"""Insight: {insight_info['name']} (ID: {insight_info['insight_id']})
HYPERLINK FORMAT: {hyperlink_format}
Description: {insight_info['description'] or 'No description'}
Query: {insight_info['query']}
Current Results: {insight_info['results']}"""

        @tool
        def reject_all_insights(reason: str) -> str:
            """Indicate that none of the insights are suitable."""
            self._evaluation_selections = {}
            self._rejection_reason = reason
            return "All insights rejected. Will create new insight."

        return [select_insight, get_insight_details, reject_all_insights]

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        search_query = state.search_insights_query

        try:
            self._current_iteration = 0
            self._load_insights_page(0)

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

        except Exception:
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

        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]

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
                                tool_content = "Page 1 data was already provided in the initial context above."
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

        # Fallback to max_insights if no results
        if not selected_insights:
            first_page_insights = self._load_insights_page(0)
            selected_insights = [insight.id for insight in first_page_insights[: self._max_insights]]

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
        if insight.filters:
            insight_type = get_insight_type_from_filters(insight.filters) or "Unknown"
        elif insight.query:
            try:
                query_dict = json.loads(insight.query) if isinstance(insight.query, str) else insight.query
                query_kind = query_dict.get("kind", "Unknown")

                if query_kind == "DataVisualizationNode":
                    source = query_dict.get("source", {})
                    if source.get("kind") == "HogQLQuery":
                        insight_type = "HogQL"
                    else:
                        insight_type = "DataVisualization"
                else:
                    insight_type = query_kind.replace("Query", "")
            except Exception:
                insight_type = "Unknown"

        # Check if insight can be visualized
        can_viz = bool(insight.query or (insight.filters and convert_filters_to_query(insight.filters)))
        viz_status = "✓ Executable" if can_viz else "✗ Not executable"

        # Get basic query info without executing
        query_info = self._get_basic_query_info_from_insight(insight)

        insight_url = f"/project/{self._team.id}/insights/{insight.short_id}"
        hyperlink_format = f"[{name}]({insight_url})"

        summary_parts = [f"ID: {insight_id} | {name} | {hyperlink_format}", f"Type: {insight_type} | {viz_status}"]

        if description:
            summary_parts.append(f"Description: {description}")

        if query_info:
            summary_parts.append(f"Query: {query_info}")

        return " | ".join(summary_parts)

    def _get_basic_query_info_from_insight(self, insight: Insight) -> str | None:
        """Extract basic query information from Insight object without execution."""
        try:
            query_dict = None

            # Parse query or convert from filters
            if insight.query:
                if isinstance(insight.query, str):
                    query_dict = json.loads(insight.query)
                elif isinstance(insight.query, dict):
                    query_dict = insight.query
            elif insight.filters:
                query_dict = convert_filters_to_query(insight.filters)

            if not query_dict:
                return None

            # Extract basic info from query
            info_parts = []

            # Get events/series info
            series = query_dict.get("series", [])
            if series:
                events = []
                for s in series:
                    if isinstance(s, dict):
                        event_name = s.get("event", s.get("name", "Unknown"))
                        events.append(event_name)
                if events:
                    # Limit to first 3 for LLM context window
                    info_parts.append(f"Events: {', '.join(events[:3])}")

            # Get date range info
            date_range = query_dict.get("dateRange", {})
            if date_range:
                date_from = date_range.get("date_from", "")
                if date_from:
                    info_parts.append(f"Period: {date_from}")

            return " | ".join(info_parts) if info_parts else None

        except Exception:
            return "Query error"

    def _process_insight_for_evaluation(self, insight: Insight, query_executor: AssistantQueryExecutor) -> dict:
        """
        Process an insight for evaluation: convert to query, execute it, and create visualization message.
        """
        insight_info = {
            "name": insight.name or insight.derived_name or "Unnamed",
            "insight_id": insight.id,
            "description": insight.description or "",
            "query": "",
            "filters": insight.filters or "",
            "results": "",
            "visualization_message": None,
        }

        try:
            query_dict = None
            query_kind = None

            # If we have a query, use it directly
            if insight.query:
                if isinstance(insight.query, str):
                    query_dict = json.loads(insight.query)
                elif isinstance(insight.query, dict):
                    query_dict = insight.query

                if query_dict:
                    query_kind = query_dict.get("kind")

            # If no query but we have filters, convert filters to query
            elif insight.filters:
                query_dict = convert_filters_to_query(insight.filters)
                if query_dict:
                    query_kind = query_dict.get("kind")

            if query_dict and query_kind:
                from ee.hogai.graph.root.nodes import MAX_SUPPORTED_QUERY_KIND_TO_MODEL

                if query_kind == "DataVisualizationNode":
                    source = query_dict.get("source")
                    if source and source.get("kind") == "HogQLQuery":
                        query_dict = source
                        query_kind = "HogQLQuery"

                if query_kind in MAX_SUPPORTED_QUERY_KIND_TO_MODEL:
                    # Execute query
                    try:
                        QueryModel = MAX_SUPPORTED_QUERY_KIND_TO_MODEL[query_kind]
                        query_obj = QueryModel.model_validate(query_dict)
                        results, _ = query_executor.run_and_format_query(query_obj)

                        insight_info["query"] = (
                            json.dumps(query_dict) if isinstance(query_dict, dict) else str(query_dict)
                        )
                        insight_info["results"] = results
                    except Exception as e:
                        insight_info["query"] = f"Failed to execute query: {str(e)}"
                        insight_info["results"] = f"Execution failed: {str(e)}"
                else:
                    insight_info["query"] = f"Query type '{query_kind}' not supported for execution"
                    insight_info["results"] = f"Query type '{query_kind}' not supported for execution"

                viz_message = self._create_visualization_message_for_insight(insight)
                insight_info["visualization_message"] = viz_message

            else:
                # No convertible query
                original_query = insight.query
                if original_query:
                    insight_info["query"] = str(original_query)
                    insight_info["results"] = "Could not convert or execute query"
                else:
                    insight_info["query"] = "No query data available"
                    insight_info["results"] = "Cannot execute - no query or filter data"

        except Exception:
            insight_info["query"] = insight.query or ""
            insight_info["results"] = "Failed to process insight"

        return insight_info

    def _create_visualization_message_for_insight(self, insight: Insight) -> VisualizationMessage | None:
        """Create a VisualizationMessage to render the insight UI."""
        try:
            query_dict = None
            query_kind = None

            # If we have a query, use it directly
            if insight.query:
                if isinstance(insight.query, str):
                    query_dict = json.loads(insight.query)
                elif isinstance(insight.query, dict):
                    query_dict = insight.query

                if query_dict:
                    query_kind = query_dict.get("kind")

            # If no query but we have filters, convert filters to query
            elif insight.filters:
                query_dict = convert_filters_to_query(insight.filters)
                if query_dict:
                    query_kind = query_dict.get("kind")

            if not query_dict or not query_kind:
                return None

            if query_kind == "DataVisualizationNode":
                source = query_dict.get("source")
                if source and source.get("kind") == "HogQLQuery":
                    query_dict = source
                    query_kind = "HogQLQuery"
                else:
                    return None

            assistant_query_type_map = {
                "TrendsQuery": AssistantTrendsQuery,
                "FunnelsQuery": AssistantFunnelsQuery,
                "RetentionQuery": AssistantRetentionQuery,
                "HogQLQuery": AssistantHogQLQuery,
            }

            if query_kind not in assistant_query_type_map:
                return None

            AssistantQueryModel = assistant_query_type_map[query_kind]
            query_obj = AssistantQueryModel.model_validate(query_dict)  # type: ignore[attr-defined]

            insight_name = insight.name or insight.derived_name or "Unnamed Insight"
            viz_message = VisualizationMessage(
                query=f"Existing insight: {insight_name}",
                plan=f"Showing existing insight: {insight_name}",
                answer=query_obj,
                id=str(uuid4()),
            )

            return viz_message

        except Exception:
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

        messages = [SystemMessage(content=system_prompt)]

        for _ in range(self._max_insights_evaluation_iterations):
            response = llm_with_tools.invoke(messages)

            if hasattr(response, "tool_calls") and response.tool_calls:
                messages.append(response)

                for tool_call in response.tool_calls:
                    if tool_call["name"] in ["select_insight", "get_insight_details", "reject_all_insights"]:
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
                viz_message = self._create_visualization_message_for_insight(selection["insight"])
                if viz_message:
                    visualization_messages.append(viz_message)
                insight = selection["insight"]
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

    def router(self, state: AssistantState) -> Literal["root", "insights"]:
        if state.root_tool_insight_plan and not state.search_insights_query:
            return "insights"
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
