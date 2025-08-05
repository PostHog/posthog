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
)
from .utils import convert_filters_to_query, can_visualize_insight, get_insight_type_from_filters, get_basic_query_info

from posthog.models import InsightViewed


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
                name = insight.get("insight__name") or insight.get("insight__derived_name", "Unnamed")
                description = insight.get("insight__description", "")
                insight_id = insight.get("insight_id")

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

            name = insight.get("insight__name") or insight.get("insight__derived_name", "Unnamed")
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

            return f"""Insight: {insight_info['name']} (ID: {insight_info['insight_id']})
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
                return self._create_error_response("No insights found in the database.", state.root_tool_call_id)

            selected_insights = self._search_insights_iteratively(search_query or "")

            evaluation_result = self._evaluate_insights_with_tools(
                selected_insights, search_query or "", max_selections=1
            )

            if evaluation_result["should_use_existing"]:
                # Create visualization messages for the insights to show actual charts
                messages_to_return = []

                formatted_content = f"**Evaluation Result**: {evaluation_result['explanation']}"

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
                return PartialAssistantState(
                    root_tool_insight_plan=search_query,
                    search_insights_query=None,
                )

        except Exception:
            return self._create_error_response(
                "INSTRUCTIONS: Tell the user that you encountered an issue while searching for insights and suggest they try again with a different search term.",
                state.root_tool_call_id,
            )

    def _get_insights_queryset(self):
        return (
            InsightViewed.objects.filter(team__project_id=self._team.project_id)
            .select_related(
                "insight__name",
                "insight__description",
                "insight__derived_name",
                "insight__team",
                "insight__short_id",
                "insight__query",
                "insight__filters",
            )
            .order_by("insight_id", "-last_viewed_at")
            .distinct("insight_id")
        )

    def _get_total_insights_count(self) -> int:
        if self._total_insights_count is None:
            self._total_insights_count = self._get_insights_queryset().count()
        return self._total_insights_count

    def _load_insights_page(self, page_number: int) -> list[dict]:
        """Load a specific page of insights from database."""
        if page_number in self._loaded_pages:
            return self._loaded_pages[page_number]

        start_idx = page_number * self._page_size
        end_idx = start_idx + self._page_size

        insights_qs = self._get_insights_queryset()[start_idx:end_idx]

        page_insights = list(
            insights_qs.values(
                "insight_id",
                "insight__name",
                "insight__description",
                "insight__derived_name",
                "insight__query",
                "insight__short_id",
                "insight__filters",
            )
        )

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
            selected_insights = [insight["insight_id"] for insight in first_page_insights[: self._max_insights]]

        return selected_insights[: self._max_insights]

    def _format_insights_page(self, page_number: int) -> str:
        """Format a page of insights for display."""
        page_insights = self._load_insights_page(page_number)

        if not page_insights:
            return "No insights available on this page."

        formatted_insights = []
        for insight in page_insights:
            name = insight.get("insight__name") or insight.get("insight__derived_name", "Unnamed")
            description = insight.get("insight__description", "")
            insight_id = insight.get("insight_id")

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
                all_ids.add(insight["insight_id"])
        return all_ids

    def _find_insight_by_id(self, insight_id: int) -> dict | None:
        """Find an insight by ID across all loaded pages."""
        for page_insights in self._loaded_pages.values():
            for insight in page_insights:
                if insight["insight_id"] == insight_id:
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

    def _create_enhanced_insight_summary(self, insight: dict) -> str:
        """Create enhanced summary with metadata and basic execution info."""
        insight_id = insight.get("insight_id")
        name = insight.get("insight__name") or insight.get("insight__derived_name", "Unnamed")
        description = insight.get("insight__description", "")

        insight_type = "Unknown"
        if insight.get("insight__filters"):
            insight_type = get_insight_type_from_filters(insight["insight__filters"]) or "Unknown"
        elif insight.get("insight__query"):
            try:
                query_dict = (
                    json.loads(insight["insight__query"])
                    if isinstance(insight["insight__query"], str)
                    else insight["insight__query"]
                )
                insight_type = query_dict.get("kind", "Unknown").replace("Query", "")
            except Exception:
                insight_type = "Unknown"

        can_viz = can_visualize_insight(insight)
        viz_status = "✓ Executable" if can_viz else "✗ Not executable"

        # Get basic query info without executing
        query_info = get_basic_query_info(insight)

        summary_parts = [f"ID: {insight_id} | {name}", f"Type: {insight_type} | {viz_status}"]

        if description:
            summary_parts.append(f"Description: {description}")

        if query_info:
            summary_parts.append(f"Query: {query_info}")

        return " | ".join(summary_parts)

    def _convert_insight_to_query(self, insight: dict) -> tuple[dict | None, str | None]:
        """
        Convert an insight (with query or legacy filters) to a modern query format.
        """
        try:
            insight_query = insight.get("insight__query")
            insight_filters = insight.get("insight__filters")

            # If we have a query, use it
            if insight_query:
                if isinstance(insight_query, str):
                    query_dict = json.loads(insight_query)
                elif isinstance(insight_query, dict):
                    query_dict = insight_query
                else:
                    return None, None

            # If no query but we have filters, try to convert filters to query
            elif insight_filters:
                query_dict = convert_filters_to_query(insight_filters)
                if not query_dict:
                    return None, None

            else:
                # No query and no filters
                return None, None

            query_kind = query_dict.get("kind")
            return query_dict, query_kind

        except Exception:
            return None, None

    def _process_insight_for_evaluation(self, insight: dict, query_executor: AssistantQueryExecutor) -> dict:
        """
        Process an insight for evaluation: convert to query, execute it, and create visualization message.
        """
        insight_info = {
            "name": insight.get("insight__name") or insight.get("insight__derived_name", "Unnamed"),
            "insight_id": insight.get("insight_id"),
            "description": insight.get("insight__description", ""),
            "query": "",
            "filters": insight.get("insight__filters", ""),
            "results": "",
            "visualization_message": None,
        }

        try:
            query_dict, query_kind = self._convert_insight_to_query(insight)

            if query_dict and query_kind:
                from ee.hogai.graph.root.nodes import MAX_SUPPORTED_QUERY_KIND_TO_MODEL

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
                original_query = insight.get("insight__query")
                if original_query:
                    insight_info["query"] = str(original_query)
                    insight_info["results"] = "Could not convert or execute query"
                else:
                    insight_info["query"] = "No query data available"
                    insight_info["results"] = "Cannot execute - no query or filter data"

        except Exception:
            insight_info["query"] = insight.get("insight__query", "")
            insight_info["results"] = "Failed to process insight"

        return insight_info

    def _create_visualization_message_for_insight(self, insight: dict) -> VisualizationMessage | None:
        """Create a VisualizationMessage to render the insight UI."""
        try:
            query_dict, query_kind = self._convert_insight_to_query(insight)
            if not query_dict or not query_kind:
                return None

            assistant_query_type_map = {
                "TrendsQuery": AssistantTrendsQuery,
                "FunnelsQuery": AssistantFunnelsQuery,
                "RetentionQuery": AssistantRetentionQuery,
                "HogQLQuery": AssistantHogQLQuery,
            }

            if not query_kind or query_kind not in assistant_query_type_map:
                return None

            AssistantQueryModel = assistant_query_type_map[query_kind]
            query_obj = AssistantQueryModel.model_validate(query_dict)  # type: ignore[attr-defined]

            insight_name = insight.get("insight__name") or insight.get("insight__derived_name", "Unnamed Insight")
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

        system_prompt = f"""You are evaluating existing insights to determine which ones (if any) match the user's query.

User Query: {user_query}

Available Insights:
{chr(10).join(insights_summary)}

Instructions:
1. {selection_instruction}
2. Use get_insight_details if you need more information about an insight before deciding
3. If you find suitable insights, use select_insight for each one with a clear explanation of why it matches
4. If none of the insights are suitable, use reject_all_insights with a reason
5. Be selective - only choose insights that truly match the user's needs
6. When multiple insights could work, prioritize:
   - Exact matches over partial matches
   - More specific insights over generic ones
   - Insights with clear descriptions over vague ones"""

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
                insight_name = selection["insight"].get("insight__name") or selection["insight"].get(
                    "insight__derived_name", "Unnamed"
                )
                explanations.append(f"- {insight_name}: {selection['explanation']}")

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
