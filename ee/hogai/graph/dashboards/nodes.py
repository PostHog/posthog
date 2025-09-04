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
    HYPERLINK_USAGE_INSTRUCTIONS,
    QUERIES_WITHOUT_INSIGHTS_MESSAGE_TEMPLATE,
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
        self, progress_message: str, substeps: list[str] | None = None, writer: StreamWriter | None = None
    ) -> None:
        if not writer:
            logger.warning("Cannot stream reasoning message!")
            return

        try:
            display_content = progress_message
            if substeps:
                display_content += "\n" + "\n".join(f"• {step}" for step in substeps)

            message_chunk = AIMessageChunk(
                content="",
                additional_kwargs={"reasoning": {"summary": [{"text": f"**{display_content}**"}]}},
            )
            message = (message_chunk, {"langgraph_node": AssistantNodeName.DASHBOARD_CREATOR})

            writer(("dashboard_creator_node", "messages", message))

        except Exception as e:
            logger.exception("Failed to stream reasoning message", error=str(e), content=progress_message)

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        if not state.create_dashboard_query:
            return self._create_error_response(
                "Dashboard creation query is required", state.root_tool_call_id or "unknown"
            )

        if not state.search_insights_queries:
            return self._create_error_response(
                "Search insights queries are required", state.root_tool_call_id or "unknown"
            )

        try:
            # Step 1: Search for existing insights
            self._stream_reasoning(
                progress_message=f"Searching for {len(state.search_insights_queries)} insights",
                writer=self._get_stream_writer(),
            )

            query_to_insight_ids, last_messages = await self._search_insights(state)

            self._stream_reasoning(
                progress_message=f"Found {len(query_to_insight_ids)} insights", writer=self._get_stream_writer()
            )

            left_to_create = [
                search_query
                for search_query in state.search_insights_queries
                if search_query not in query_to_insight_ids
            ]

            query_to_insight_ids, last_messages_created = await self._create_insights_with_subgraph(
                left_to_create, query_to_insight_ids, state, config
            )

            all_insight_ids = list(
                {insight_id for insight_set in query_to_insight_ids.values() for insight_id in insight_set}
            )
            last_messages = last_messages + last_messages_created

            if not all_insight_ids:
                return self._create_no_insights_response(state.root_tool_call_id or "unknown", last_messages)

            dashboard_name = await self._generate_dashboard_name(
                state.create_dashboard_query, last_messages, all_insight_ids
            )

            dashboard, all_insights = await self._create_dashboard_with_insights(dashboard_name, all_insight_ids)

            queries_no_insights = [
                query for query in state.search_insights_queries if query not in query_to_insight_ids
            ]
            return self._create_success_response(
                dashboard, all_insights, state.root_tool_call_id or "unknown", queries_no_insights
            )
        except Exception as e:
            logger.exception(
                f"Error in DashboardCreatorNode: {e}",
                extra={
                    "team_id": getattr(self._team, "id", "unknown"),
                    "error": str(e),
                },
                exc_info=True,
            )
            return self._create_error_response(DASHBOARD_CREATION_ERROR_MESSAGE, state.root_tool_call_id or "unknown")

    async def _search_insights(self, state: AssistantState) -> tuple[dict[str, list[int]], list[str]]:
        """Search for existing insights using the InsightSearchNode."""
        last_messages = []
        query_to_insight_ids = {}
        total_to_search = len(state.search_insights_queries)
        index = 0
        try:
            for search_query in state.search_insights_queries:
                index += 1
                # Create a minimal state for insight search
                search_state = AssistantState(
                    root_tool_call_id=state.root_tool_call_id,
                    create_dashboard_query=state.create_dashboard_query,
                    search_insights_query=search_query,
                    insight_ids=None,
                )
                self._stream_reasoning(
                    progress_message=f"Searching {index}/{total_to_search} insights", writer=self._get_stream_writer()
                )
                insight_search_node = InsightSearchNode(team=self._team, user=self._user)
                search_result = await insight_search_node.arun(search_state, {})

                insight_ids = search_result.insight_ids if search_result and search_result.insight_ids else []
                # Reason for selecting the insights
                if insight_ids:
                    last_messages.append(
                        search_result.messages[-2].content if search_result and search_result.messages else ""
                    )

                    if search_query not in query_to_insight_ids:
                        query_to_insight_ids[search_query] = set(insight_ids)
                    else:
                        query_to_insight_ids[search_query].update(set(insight_ids))

            return query_to_insight_ids, last_messages

        except Exception as e:
            logger.exception(f"Error searching for insights: {e}")
            return [], []

    def _build_insight_url(self, id: int) -> str:
        """Build the URL for an insight."""
        return f"/project/{self._team.id}/insights/{id}"

    def _build_dashboard_url(self, id: int) -> str:
        """Build the URL for a dashboard."""
        return f"/project/{self._team.id}/dashboard/{id}"

    async def _create_insights_with_subgraph(
        self,
        left_to_create: list[str],
        query_to_insight_ids: dict[str, set[int]],
        state: AssistantState,
        config: RunnableConfig,
    ) -> tuple[dict[str, set[int]], list[str]]:
        """Create insights using the insights subgraph if no existing insights are found."""
        try:
            last_messages = []
            # Import the insights graph here to avoid circular imports
            from ee.hogai.graph.graph import InsightsAssistantGraph

            total_to_create = len(left_to_create)
            for query in left_to_create:
                # Create state for insights creation
                insights_state = AssistantState(
                    root_tool_insight_plan=query,
                    # search_insights_queries=None,
                    root_tool_call_id=state.root_tool_call_id,
                    messages=state.messages,
                    create_dashboard_query=state.create_dashboard_query,
                    insight_ids=None,
                )

                graph = InsightsAssistantGraph(self._team, self._user).compile_full_graph()

                result = await graph.ainvoke(insights_state, config=config)
                insight_state = AssistantState.model_validate(result)
                created_insight_ids = insight_state.insight_ids if insight_state and insight_state.insight_ids else []

                if created_insight_ids:
                    self._stream_reasoning(
                        progress_message=f"Created {len(created_insight_ids)}/{total_to_create} insights",
                        writer=self._get_stream_writer(),
                    )
                    if query not in query_to_insight_ids:
                        query_to_insight_ids[query] = set(created_insight_ids)
                    else:
                        query_to_insight_ids[query].update(set(created_insight_ids))
                    last_messages.append(f"Created insight for the query {query}")
                else:
                    self._stream_reasoning(
                        progress_message=f"Failed to create insights for {query}", writer=self._get_stream_writer()
                    )
                    last_messages.append(f"Failed to create insight for the query {query}.")
            return query_to_insight_ids, last_messages
        except Exception as e:
            logger.exception(f"Error creating insights with subgraph: {e}")
            return {}, []

    async def _generate_dashboard_name(self, query: str, last_messages: list[str], insight_ids: list[int]) -> str:
        """Generate a dashboard name based on the query and insights."""
        self._stream_reasoning(progress_message="Generating dashboard name", writer=self._get_stream_writer())
        try:
            insights_summary = "\n".join(last_messages)

            messages = [
                SystemMessage(
                    content=DASHBOARD_NAME_GENERATION_SYSTEM_PROMPT.format(
                        user_query=query, insights_summary=insights_summary
                    )
                ),
                HumanMessage(content="Generate the dashboard name."),
            ]

            response = await self._model.ainvoke(messages)
            dashboard_name = response.content.strip() if hasattr(response, "content") else "Analytics Dashboard"

            return dashboard_name[:50]

        except Exception as e:
            logger.exception(f"Error generating dashboard name: {e}")
            return "Analytics Dashboard"

    async def _create_dashboard_with_insights(self, dashboard_name: str, insights: list[int]) -> Dashboard:
        """Create a dashboard and add the insights to it."""
        self._stream_reasoning(progress_message="Saving your dashboard", writer=self._get_stream_writer())

        @database_sync_to_async
        def create_dashboard_sync():
            all_insights = []
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
                all_insights.append(insight)

            return dashboard, all_insights

        return await create_dashboard_sync()

    def _create_success_response(
        self,
        dashboard: Dashboard,
        insights: list[Insight],
        tool_call_id: str,
        queries_without_insights: list[str] | None = None,
    ) -> PartialAssistantState:
        """Create a success response with dashboard details."""
        insight_count = len(insights)
        insight_plural = "" if insight_count == 1 else "s"

        insights_list = "\n".join(
            [f"[{insight.name}]({self._build_insight_url(insight.short_id)})" for insight in insights]
        )

        success_message = DASHBOARD_SUCCESS_MESSAGE_TEMPLATE.format(
            dashboard_name=dashboard.name,
            insight_count=insight_count,
            insight_plural=insight_plural,
            insights_list=insights_list,
            dashboard_url=self._build_dashboard_url(dashboard.id),
        )

        if queries_without_insights:
            success_message = success_message + QUERIES_WITHOUT_INSIGHTS_MESSAGE_TEMPLATE.format(
                queries_without_insights="\n".join([f"• {query}" for query in queries_without_insights])
            )

        success_message = success_message + HYPERLINK_USAGE_INSTRUCTIONS

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
            search_insights_queries=None,
            root_tool_call_id=None,
        )

    def _create_no_insights_response(self, tool_call_id: str, subgraph_last_message: str) -> PartialAssistantState:
        """Create response when no insights could be found or created."""
        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(
                    content=DASHBOARD_NO_INSIGHTS_MESSAGE.format(subgraph_last_message=subgraph_last_message),
                    tool_call_id=tool_call_id,
                    id=str(uuid4()),
                ),
            ],
            create_dashboard_query=None,
            root_tool_call_id=None,
            search_insights_queries=None,
            insight_ids=None,
        )

    def _create_error_response(self, content: str, tool_call_id: str) -> PartialAssistantState:
        """Create error response for the assistant."""
        return PartialAssistantState(
            messages=[
                AssistantToolCallMessage(
                    content=content,
                    tool_call_id=tool_call_id,
                    id=str(uuid4()),
                ),
            ],
            create_dashboard_query=None,
            root_tool_call_id=None,
            search_insights_queries=None,
            insight_ids=None,
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
                ),
            ],
            create_dashboard_query=None,
            search_insights_queries=None,
            root_tool_call_id=None,
            insight_ids=None,
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
