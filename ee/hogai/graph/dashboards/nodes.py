import time
from typing import Literal
from uuid import uuid4

import structlog
from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.config import get_stream_writer
from langgraph.types import StreamWriter

from posthog.schema import AssistantToolCallMessage

from posthog.models import Dashboard, DashboardTile, Insight
from posthog.sync import database_sync_to_async

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.insights.nodes import InsightSearchNode
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState

from .prompts import (
    DASHBOARD_CREATION_ERROR_MESSAGE,
    DASHBOARD_NAME_GENERATION_SYSTEM_PROMPT,
    DASHBOARD_NO_INSIGHTS_MESSAGE,
    DASHBOARD_SUCCESS_MESSAGE_TEMPLATE,
)

logger = structlog.get_logger(__name__)


class DashboardCreatorNode(AssistantNode):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stream_writer = None

    def _get_stream_writer(self) -> StreamWriter | None:
        if self._stream_writer is None:
            try:
                self._stream_writer = get_stream_writer()
            except Exception:
                self._stream_writer = None
        return self._stream_writer

    def _stream_reasoning(
        self, content: str, substeps: list[str] | None = None, writer: StreamWriter | None = None
    ) -> None:
        if not writer:
            logger.warning("Cannot stream reasoning message!")
            return

        try:
            display_content = content
            if substeps:
                display_content += "\n" + "\n".join(f"• {step}" for step in substeps)

            message_chunk = AIMessageChunk(
                content="",
                additional_kwargs={"reasoning": {"summary": [{"text": f"**{display_content}**"}]}},
            )
            message = (message_chunk, {"langgraph_node": AssistantNodeName.DASHBOARD_CREATOR})

            writer(("dashboard_creator_node", "messages", message))

        except Exception as e:
            logger.exception("Failed to stream reasoning message", error=str(e), content=content)

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        start_time = time.time()
        conversation_id = config.get("configurable", {}).get("thread_id", "unknown")
        writer = self._get_stream_writer()

        if not state.create_dashboard_query:
            return self._create_error_response(
                "Dashboard creation query is required", state.root_tool_call_id or "unknown"
            )

        if not state.search_insights_query:
            return self._create_error_response(
                "Search insights query is required", state.root_tool_call_id or "unknown"
            )

        try:
            self._stream_reasoning(
                content="Creating your dashboard",
                substeps=["Searching for relevant insights", "Generating dashboard name"],
                writer=writer,
            )

            # Step 1: Search for existing insights
            insights, last_message = await self._search_for_insights(state.search_insights_query, writer)

            # Step 2: If no insights found, try to create them using insights subgraph
            if not insights:
                subgraph_result = await self._create_insights_with_subgraph(state, config, writer)

                # Check if subgraph asked for help (returns help message string or None)
                if isinstance(subgraph_result, str):
                    return self._create_help_request_response(state.root_tool_call_id or "unknown", subgraph_result)
                elif subgraph_result is None:
                    return self._create_help_request_response(state.root_tool_call_id or "unknown")
                elif isinstance(subgraph_result, list):
                    insights = subgraph_result
                else:
                    insights = []

            # Step 3: If still no insights, return error
            if not insights:
                return self._create_no_insights_response(state.root_tool_call_id or "unknown")

            # Step 4: Generate dashboard name
            dashboard_name = await self._generate_dashboard_name(state.create_dashboard_query, last_message)

            # Step 5: Create the dashboard
            dashboard = await self._create_dashboard_with_insights(dashboard_name, insights, writer)
            return self._create_success_response(dashboard, insights, state.root_tool_call_id or "unknown")

        except Exception as e:
            logger.error(
                f"Error in DashboardCreatorNode: {e}",
                extra={
                    "team_id": getattr(self._team, "id", "unknown"),
                    "conversation_id": conversation_id,
                    "execution_time_ms": round((time.time() - start_time) * 1000, 2),
                    "error": str(e),
                },
                exc_info=True,
            )
            return self._create_error_response(DASHBOARD_CREATION_ERROR_MESSAGE, state.root_tool_call_id or "unknown")

    async def _search_for_insights(self, query: str, writer: StreamWriter | None) -> list[int]:
        """Search for existing insights using the InsightSearchNode."""
        try:
            self._stream_reasoning(content="Searching for existing insights", writer=writer)

            # Create a minimal state for insight search
            search_state = AssistantState(
                search_insights_query=query,
                root_tool_call_id="dashboard_creator_search",
            )

            insight_search_node = InsightSearchNode(team=self._team, user=self._user)

            search_result = await insight_search_node.arun(search_state, {})
            insight_ids = search_result.insight_ids if search_result and search_result.insight_ids else []

            last_message = search_result.messages[-1] if search_result and search_result.messages else None

            return insight_ids[:5], last_message  # Limit to 5 insights for dashboard

        except Exception as e:
            logger.warning(f"Error searching for insights: {e}")
            return [], None

    async def _create_insights_with_subgraph(
        self, state: AssistantState, config: RunnableConfig, writer: StreamWriter | None
    ) -> list[int] | str | None:
        """Create insights using the insights subgraph if no existing insights are found.
        Returns:
            list[int]: List of created insight IDs
            str: Help message from the subgraph if user help was requested
            None: If the subgraph asked for user help but no message was found
        """
        try:
            self._stream_reasoning(content="Creating new insights for your dashboard", writer=writer)

            # Import the insights graph here to avoid circular imports
            from collections.abc import AsyncIterator
            from typing import Any

            from posthog.schema import AssistantMessage

            from ee.hogai.graph.graph import InsightsAssistantGraph

            # Create state for insights creation
            insights_state = AssistantState(
                root_tool_insight_plan=state.search_insights_query,
                search_insights_query=None,
                root_tool_call_id=state.root_tool_call_id,
                messages=state.messages,
                create_dashboard_query=state.create_dashboard_query,
            )

            graph = InsightsAssistantGraph(self._team, self._user).compile_full_graph()

            last_message = state.messages[-1]
            if not isinstance(last_message, AssistantMessage):
                raise ValueError("Last message is not an AssistantMessage")
            if last_message.tool_calls is None or len(last_message.tool_calls) == 0:
                raise ValueError("Last message has no tool calls")

            generator: AsyncIterator[Any] = graph.astream(
                insights_state, config=config, stream_mode=["messages", "values", "updates", "debug"], subgraphs=True
            )

            # Stream chunks but handle message chunks properly to avoid truncation
            async for chunk in generator:
                # For message chunks, ensure we show the full content
                if isinstance(chunk, dict) and "messages" in chunk:
                    # Extract and display the actual message content
                    for message_chunk, _ in chunk["messages"]:
                        if hasattr(message_chunk, "content") and message_chunk.content:
                            # Show the actual message content in a clean format
                            self._stream_reasoning(content=f"Insight creation: {message_chunk.content}", writer=writer)
                else:
                    # Stream other chunks directly
                    writer(chunk)

            snapshot = await graph.aget_state(config)

            help_message = None

            # Check snapshot metadata to distinguish help request vs successful completion
            if hasattr(snapshot, "metadata") and snapshot.metadata:
                # Look for help messages in metadata writes
                if "writes" in snapshot.metadata:
                    for node_name, node_writes in snapshot.metadata["writes"].items():
                        if node_name == "query_executor":
                            if "insight_ids" in node_writes:
                                return node_writes["insight_ids"]
                        if isinstance(node_writes, dict) and "messages" in node_writes:
                            messages = node_writes["messages"]
                            if isinstance(messages, list):
                                for msg in messages:
                                    # Check for help request messages
                                    if (
                                        hasattr(msg, "content")
                                        and msg.content
                                        and isinstance(msg.content, str)
                                        and "The agent has requested help from the user:" in msg.content
                                    ):
                                        raw_help_message = msg.content

                                        # Clean up the help message - extract the actual request
                                        if "request='" in raw_help_message:
                                            start = raw_help_message.find("request='") + len("request='")
                                            end = raw_help_message.rfind("'")
                                            if start < end:
                                                help_message = raw_help_message[start:end]
                                            else:
                                                help_message = raw_help_message
                                        else:
                                            help_message = raw_help_message

                                        return help_message
            return []

        except Exception as e:
            logger.warning(f"Error creating insights with subgraph: {e}")
            return []

    async def _generate_dashboard_name(self, query: str, last_message) -> str:
        """Generate a dashboard name based on the query and insights."""
        try:
            # Extract insights summary from different message types
            insights_summary = ""
            if hasattr(last_message, "content") and last_message.content:
                insights_summary = str(last_message.content)
            elif hasattr(last_message, "answer") and last_message.answer:
                insights_summary = str(last_message.answer)
            else:
                insights_summary = "Found relevant insights for dashboard creation"

            messages = [
                SystemMessage(
                    content=DASHBOARD_NAME_GENERATION_SYSTEM_PROMPT.format(
                        user_query=query, insights_summary=insights_summary
                    )
                ),
                HumanMessage(content="Generate the dashboard name."),
            ]

            response = await self._model.ainvoke(messages)
            dashboard_name = response.content.strip() if hasattr(response, "content") else "New Dashboard"

            # Fallback if the model returns something unexpected
            if not dashboard_name or len(dashboard_name) > 100:
                dashboard_name = "Analytics Dashboard"
            return dashboard_name

        except Exception as e:
            logger.warning(f"Error generating dashboard name: {e}")
            return "Analytics Dashboard"

    async def _create_dashboard_with_insights(
        self, dashboard_name: str, insights: list[int], writer: StreamWriter | None
    ) -> Dashboard:
        """Create a dashboard and add the insights to it."""
        self._stream_reasoning(content="Building your dashboard", writer=writer)

        @database_sync_to_async
        def create_dashboard_sync():
            # Create the dashboard
            dashboard = Dashboard.objects.create(
                name=dashboard_name,
                team=self._team,
                created_by=self._user,
            )

            # Add insights to the dashboard via DashboardTile
            for insight_id in insights:
                insight = Insight.objects.get(id=insight_id)
                DashboardTile.objects.create(
                    dashboard=dashboard,
                    insight=insight,
                    layouts={},  # Default layout
                )

            return dashboard

        return await create_dashboard_sync()

    def _create_success_response(
        self, dashboard: Dashboard, insights: list[int], tool_call_id: str
    ) -> PartialAssistantState:
        """Create a success response with dashboard details."""
        insight_count = len(insights)
        insight_plural = "" if insight_count == 1 else "s"

        insights_list = "\n".join([f"• {insight_id}" for insight_id in insights])

        success_message = DASHBOARD_SUCCESS_MESSAGE_TEMPLATE.format(
            dashboard_name=dashboard.name if dashboard else "New Dashboard",
            insight_count=insight_count,
            insight_plural=insight_plural,
            insights_list=insights_list,
            dashboard_id=dashboard.id if dashboard else "unknown",
        )

        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(
                    content=success_message,
                    tool_call_id=tool_call_id,
                    id=str(uuid4()),
                    visible=True,
                ),
            ],
            create_dashboard_query=None,
            search_insights_query=None,
            root_tool_call_id=None,
        )

    def _create_no_insights_response(self, tool_call_id: str) -> PartialAssistantState:
        """Create response when no insights could be found or created."""
        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(
                    content=DASHBOARD_NO_INSIGHTS_MESSAGE,
                    tool_call_id=tool_call_id,
                    id=str(uuid4()),
                    visible=True,
                ),
            ],
            create_dashboard_query=None,
            root_tool_call_id=None,
            search_insights_query=None,
        )

    def _create_error_response(self, content: str, tool_call_id: str) -> PartialAssistantState:
        """Create error response for the assistant."""
        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(
                    content=content,
                    tool_call_id=tool_call_id,
                    id=str(uuid4()),
                    visible=True,
                ),
            ],
            create_dashboard_query=None,
            root_tool_call_id=None,
        )

    def _create_help_request_response(
        self, tool_call_id: str, help_message: str | None = None
    ) -> PartialAssistantState:
        """Create response when the insights subgraph asks for user help."""
        content = (
            help_message
            if help_message
            else "I need more information to create insights for your dashboard. Could you provide more specific details about what data or metrics you'd like to visualize?"
        )

        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(
                    content=content,
                    tool_call_id=tool_call_id,
                    id=str(uuid4()),
                    visible=True,
                ),
            ],
            create_dashboard_query=None,
            search_insights_query=None,
            root_tool_call_id=None,
        )

    def router(self, state: AssistantState) -> Literal["root"]:
        return "root"

    @property
    def _model(self):
        return ChatOpenAI(
            model="gpt-4.1-mini",
            temperature=0.3,
            max_completion_tokens=500,
            streaming=True,
            stream_usage=True,
            max_retries=3,
        )
