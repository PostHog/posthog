from typing import Literal
from uuid import uuid4
import time

from langchain_core.runnables import RunnableConfig
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

import structlog


from ee.hogai.utils.graph_states import AssistantGraphState, PartialAssistantGraphState
from posthog.schema import AssistantToolCallMessage
from ee.hogai.graph.base import AssistantNode
from .prompts import ITERATIVE_SEARCH_SYSTEM_PROMPT, ITERATIVE_SEARCH_USER_PROMPT

from posthog.models import InsightViewed


class InsightSearchNode(AssistantNode):
    logger = structlog.get_logger(__name__)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_page = 0
        self._page_size = 300
        self._max_iterations = 6
        self._current_iteration = 0
        self._all_insights = []

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

    def run(self, state: AssistantGraphState, config: RunnableConfig) -> PartialAssistantGraphState | None:
        start_time = time.time()
        search_query = state.search_insights_query
        conversation_id = config.get("configurable", {}).get("thread_id", "unknown")

        try:
            self._current_iteration = 0
            self._load_all_insights()

            if not self._all_insights:
                return self._create_error_response("No insights found in the database.", state.root_tool_call_id)

            selected_insights = self._search_insights_iteratively(search_query or "")

            formatted_content = self._format_search_results(selected_insights, search_query or "")

            execution_time = time.time() - start_time
            self.logger.info(
                f"Iterative insight search completed",
                extra={
                    "team_id": getattr(self._team, "id", "unknown"),
                    "conversation_id": conversation_id,
                    "query_length": len(search_query) if search_query else 0,
                    "results_count": len(selected_insights),
                    "execution_time_ms": round(execution_time * 1000, 2),
                    "iterations": self._current_iteration,
                },
            )

            return PartialAssistantGraphState(
                messages=[
                    AssistantToolCallMessage(
                        content=formatted_content,
                        tool_call_id=state.root_tool_call_id or "unknown",
                        id=str(uuid4()),
                    ),
                ],
                search_insights_query=None,
                root_tool_call_id=None,
            )

        except Exception as e:
            execution_time = time.time() - start_time
            self.logger.exception(
                f"Iterative insight search failed",
                extra={
                    "team_id": getattr(self._team, "id", "unknown"),
                    "conversation_id": conversation_id,
                    "query_length": len(search_query) if search_query else 0,
                    "execution_time_ms": round(execution_time * 1000, 2),
                    "error": str(e),
                },
            )

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

            except Exception as e:
                self.logger.warning(f"Search iteration failed: {e}")
                break

        # Fallback to first 3 insights if no results
        if not selected_insights:
            selected_insights = [insight["insight_id"] for insight in self._all_insights[:3]]

        # Limit to 3 insights
        return selected_insights[:3]

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
        """Parse insight IDs from LLM response."""
        import re

        # Look for numbers in the response
        numbers = re.findall(r"\b\d+\b", response_content)

        # Convert to integers and validate against available insights
        available_ids = {insight["insight_id"] for insight in self._all_insights}
        valid_ids = []

        for num_str in numbers:
            insight_id = int(num_str)
            if insight_id in available_ids:
                valid_ids.append(insight_id)

        # Limit to 3 insights
        return valid_ids[:3]

    def _format_search_results(self, selected_insights: list[int], search_query: str) -> str:
        """Format final search results for display."""
        if not selected_insights:
            return f"No insights found matching '{search_query or 'your search'}'.\n\nSuggest that the user try:\n- Using different keywords\n- Searching for broader terms\n- Creating a new insight instead"

        insight_details = []
        for insight_id in selected_insights:
            insight = next((i for i in self._all_insights if i["insight_id"] == insight_id), None)
            if insight:
                insight_details.append(insight)

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

            if description:
                result_block = f"""**{i}. {name}**
Description: {description}
[View Insight →]({insight_url})"""
            else:
                result_block = f"""**{i}. {name}**
[View Insight →]({insight_url})"""

            formatted_results.append(result_block)

        content = header + "\n\n".join(formatted_results)
        content += "\n\nINSTRUCTIONS: Ask the user if they want to modify one of these insights, or use them as a starting point for a new one."

        return content

    def _create_error_response(self, content: str, tool_call_id: str | None) -> PartialAssistantGraphState:
        """Create error response for the assistant."""
        return PartialAssistantGraphState(
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

    def router(self, state: AssistantGraphState) -> Literal["end", "root"]:
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
