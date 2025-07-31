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
from .prompts import INSIGHT_EVALUATION_SYSTEM_PROMPT, ITERATIVE_SEARCH_SYSTEM_PROMPT, ITERATIVE_SEARCH_USER_PROMPT
from .utils import convert_legacy_filters_to_query

from posthog.models import InsightViewed


class InsightSearchNode(AssistantNode):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_page = 0
        self._page_size = 300
        self._max_iterations = 6
        self._current_iteration = 0
        self._all_insights = []
        self._max_insights = 3

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
            start_idx = page_number * self._page_size
            end_idx = start_idx + self._page_size

            page_insights = self._all_insights[start_idx:end_idx]

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

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        search_query = state.search_insights_query

        try:
            self._current_iteration = 0
            self._load_all_insights()

            if not self._all_insights:
                return self._create_error_response("No insights found in the database.", state.root_tool_call_id)

            selected_insights = self._search_insights_iteratively(search_query or "")

            evaluation_result = self._evaluate_insights_for_creation(selected_insights, search_query)

            if evaluation_result["should_use_existing"]:
                # Create visualization messages for the insights to show actual charts
                messages_to_return = []

                formatted_content = f"**MANDATORY HYPERLINK RULE**: Always use clickable links for insight names. Replace 'Weekly signups' with '[Weekly signups](URL)', 'User Signups' with '[User Signups](Insight URL)', etc.\n\n**Evaluation Result**: {evaluation_result['explanation']}"

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

    def _load_all_insights(self) -> None:
        """Load all insights from database into memory for pagination."""
        insights_qs = (
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

        self._all_insights = list(
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

    def _search_insights_iteratively(self, search_query: str) -> list[int]:
        """Execute iterative insight search with LLM and tool calling."""
        first_page = self._format_insights_page(0)

        total_pages = (len(self._all_insights) + self._page_size - 1) // self._page_size
        has_pagination = total_pages > 1

        pagination_instructions = (
            "You can read additional pages using the read_insights_page(page_number) tool. "
            "Read additional pages until you have found the most relevant insights."
            f"There are {total_pages} total pages available (0-indexed)."
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
            selected_insights = [insight["insight_id"] for insight in self._all_insights[: self._max_insights]]

        return selected_insights[: self._max_insights]

    def _format_insights_page(self, page_number: int) -> str:
        """Format a page of insights for display."""
        start_idx = page_number * self._page_size
        end_idx = start_idx + self._page_size

        page_insights = self._all_insights[start_idx:end_idx]

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

    def _parse_insight_ids(self, response_content: str) -> list[int]:
        """Parse insight IDs from LLM response, removing duplicates and preserving order."""
        numbers = re.findall(r"\b\d+\b", response_content)

        # Convert to integers and validate against available insights
        available_ids = {insight["insight_id"] for insight in self._all_insights}
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

    def _format_search_results(
        self, selected_insights: list[int], search_query: str
    ) -> tuple[str, list[VisualizationMessage]]:
        """Format final search results for display."""
        if not selected_insights:
            content = f"No insights found matching '{search_query or 'your search'}'.\n\nSuggest that the user try:\n- Using different keywords\n- Searching for broader terms\n- Creating a new insight instead"
            return content, []

        insight_details = []
        query_executor = AssistantQueryExecutor(self._team, self._utc_now_datetime)
        visualization_messages = []

        for insight_id in selected_insights:
            insight = next((i for i in self._all_insights if i["insight_id"] == insight_id), None)
            if insight:
                insight_details.append(insight)
                # Create visualization message for each insight
                viz_message = self._create_visualization_message_for_insight(insight)
                if viz_message:
                    visualization_messages.append(viz_message)

        header = f"Found {len(insight_details)} insight{'s' if len(insight_details) != 1 else ''}"
        if search_query:
            header += f" matching '{search_query}'"
        header += ":\n\n"

        formatted_results = []
        for i, insight in enumerate(insight_details, 1):
            name = insight.get("insight__name") or insight.get("insight__derived_name", "Unnamed Insight")
            description = insight.get("insight__description")
            insight_short_id = insight.get("insight__short_id")
            insight_url = f"/project/{self._team.project_id}/insights/{insight_short_id}"

            # Get formatted metadata
            metadata = self._format_insight_metadata(insight)

            # Execute insight if requested
            execution_results = ""
            executed_results = self._execute_insight_for_display(insight, query_executor)
            if executed_results:
                execution_results = f"\n\n    **Current Data:**\n    ```\n    {executed_results}\n    ```"

            if description:
                result_block = f"""**{i}. {name}**
    Description: {description}{metadata}{execution_results}
    [View Insight →]({insight_url})"""
            else:
                result_block = f"""**{i}. {name}**{metadata}{execution_results}
    [View Insight →]({insight_url})"""

            formatted_results.append(result_block)

        content = header + "\n\n".join(formatted_results)

        content += f"\n\nYou found {len(insight_details)} existing insight{'s' if len(insight_details) != 1 else ''}"
        if search_query:
            content += f" related to '{search_query}'"
        content += ". Present these results to the user and ask them how they'd like to proceed. You can:"
        content += "\n- Use one of these insights as-is"
        content += (
            "\n- Modify an existing insight (propose to make the change yourself: change filters, time range, etc.)"
        )
        content += "\n- Create a completely new insight"
        content += "\n\nBe natural and conversational - don't present this as a rigid list of options."
        content += "\n\nINSTRUCTIONS: Add a link to the insight in the format [Insight Name](Insight URL) where mentioning an insight."

        return content, visualization_messages

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

            # If no query but we have filters, try to convert legacy filters to query
            elif insight_filters:
                query_dict = convert_legacy_filters_to_query(insight_filters)
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

        Returns:
            dict with keys: name, insight_id, description, query, filters, results, visualization_message
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
            query_obj = AssistantQueryModel.model_validate(query_dict)

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

    def _execute_insight_for_display(self, insight: dict, query_executor: AssistantQueryExecutor) -> str | None:
        """Execute an insight query and return formatted results for user display."""
        try:
            query_dict, query_kind = self._convert_insight_to_query(insight)
            if not query_dict or not query_kind:
                return "No query data available or could not convert"

            from ee.hogai.graph.root.nodes import MAX_SUPPORTED_QUERY_KIND_TO_MODEL

            if query_kind not in MAX_SUPPORTED_QUERY_KIND_TO_MODEL:
                return f"Query type '{query_kind}' not supported"

            QueryModel = MAX_SUPPORTED_QUERY_KIND_TO_MODEL[query_kind]
            query_obj = QueryModel.model_validate(query_dict)
            results, _ = query_executor.run_and_format_query(query_obj)
            return results

        except Exception:
            return "Could not execute query"

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

    def _evaluate_insights_for_creation(self, selected_insights: list[int], user_query: str) -> dict:
        """
        Evaluate whether found insights can be used as a starting point for the user's query.
        Executes the insights and provides results to LLM for evaluation.

        Returns:
            dict with keys:
            - should_use_existing: bool
            - explanation: str
            - visualization_messages: list[VisualizationMessage]
        """
        if not selected_insights:
            return {
                "should_use_existing": False,
                "explanation": "No insights found to evaluate.",
                "visualization_messages": [],
            }

        # Remove duplicates while preserving order
        # unique_insights = []
        # seen_ids = set()
        # for insight_id in selected_insights:
        #     if insight_id not in seen_ids:
        #         unique_insights.append(insight_id)
        #         seen_ids.add(insight_id)

        query_executor = AssistantQueryExecutor(self._team, self._utc_now_datetime)
        insights_with_results = []
        visualization_messages = []

        for insight_id in selected_insights:
            insight = next((i for i in self._all_insights if i["insight_id"] == insight_id), None)
            if not insight:
                continue

            insight_info = self._process_insight_for_evaluation(insight, query_executor)

            # Add to results (removing the visualization_message key since LLM doens't need to see this + smaller token print)
            eval_insight_info = {k: v for k, v in insight_info.items() if k != "visualization_message"}
            insights_with_results.append(eval_insight_info)

            if insight_info["visualization_message"]:
                visualization_messages.append(insight_info["visualization_message"])

        if not insights_with_results:
            return {
                "should_use_existing": False,
                "explanation": "Could not evaluate any insights.",
                "visualization_messages": [],
            }

        formatted_insights = []
        insight_hyperlinks = {}  # Store hyperlinks for later use

        for _, insight in enumerate(insights_with_results, 1):
            insight_short_id = None
            # Find the original insight data to get the short_id for hyperlink
            original_insight = next(
                (ins for ins in self._all_insights if ins["insight_id"] == insight["insight_id"]), None
            )
            if original_insight:
                insight_short_id = original_insight.get("insight__short_id")

            insight_url = (
                f"/project/{self._team.project_id}/insights/{insight_short_id}"
                if insight_short_id
                else "URL unavailable"
            )

            # Store the hyperlink for this insight
            insight_hyperlinks[insight["name"]] = f"[{insight['name']}]({insight_url})"

            formatted_insight = f"""
**Insight: {insight['name']} (ID: {insight['insight_id']})**
- Description: {insight['description'] or 'No description'}
- Query: {insight['query']}
- Results: {insight['results']}
- Filters: {insight['filters']}
- **HYPERLINK FORMAT: [{insight['name']}]({insight_url})**
"""
            formatted_insights.append(formatted_insight)

        insights_text = "\n".join(formatted_insights)

        # Use LLM to evaluate
        evaluation_prompt = INSIGHT_EVALUATION_SYSTEM_PROMPT.format(
            user_query=user_query, insights_with_results=insights_text
        )

        try:
            messages = [SystemMessage(content=evaluation_prompt)]
            response = self._model.invoke(messages)
            response_text = response.content if isinstance(response.content, str) else str(response.content)

            # Parse response to determine if we should use existing insights, not great but works for now
            should_use_existing = response_text.upper().startswith("YES")

            return {
                "should_use_existing": should_use_existing,
                "explanation": response_text,
                "visualization_messages": visualization_messages,
            }

        except Exception:
            return {
                "should_use_existing": False,
                "explanation": "Could not evaluate insights due to an error.",
                "visualization_messages": visualization_messages,
            }

    def _format_insight_metadata(self, insight: dict) -> str:
        """
        Format insight metadata into a user-friendly string.

        Args:
            insight: Insight dictionary from _all_insights

        Returns:
            Formatted metadata string
        """
        metadata_parts = []

        insight_query = insight.get("insight__query")
        if insight_query:
            try:
                if isinstance(insight_query, str):
                    query_dict = json.loads(insight_query)
                elif isinstance(insight_query, dict):
                    query_dict = insight_query
                else:
                    query_dict = {}

                query_kind = query_dict.get("kind", "Unknown")
                if query_kind in ["TrendsQuery", "FunnelsQuery", "RetentionQuery", "HogQLQuery"]:
                    readable_type = {
                        "TrendsQuery": "Trends",
                        "FunnelsQuery": "Funnel",
                        "RetentionQuery": "Retention",
                        "HogQLQuery": "SQL",
                    }.get(query_kind, query_kind)
                    metadata_parts.append(f"**Type:** {readable_type}")

            except (json.JSONDecodeError, AttributeError):
                pass

        insight_filters = insight.get("insight__filters")
        if insight_filters:
            try:
                if isinstance(insight_filters, str):
                    filters_dict = json.loads(insight_filters)
                elif isinstance(insight_filters, dict):
                    filters_dict = insight_filters
                else:
                    filters_dict = {}

                # Properties filters
                properties = filters_dict.get("properties", [])
                if properties and len(properties) > 0:
                    metadata_parts.append(f"**Filters:** {len(properties)} filter(s) applied")

                # Breakdown filters
                breakdown = filters_dict.get("breakdown")
                if breakdown:
                    metadata_parts.append(f"**Breakdown:** {breakdown}")

            except (json.JSONDecodeError, AttributeError):
                pass

        if metadata_parts:
            return "\n" + "\n".join(metadata_parts)
        else:
            return ""

    def router(self, state: AssistantState) -> Literal["end", "root", "insights"]:
        # Check if we need to continue with insight creation after evaluation
        # if state.root_tool_insight_plan and not state.search_insights_query:
        if state.root_tool_insight_plan:
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
