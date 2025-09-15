import uuid
from typing import Any, Literal, Union
from uuid import uuid4

import structlog
from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.config import get_stream_writer
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StreamWriter
from pydantic import BaseModel

from posthog.schema import (
    AssistantHogQLQuery,
    AssistantToolCallMessage,
    TaskExecutionItem,
    TaskExecutionMessage,
    TaskExecutionStatus,
)

from posthog.exceptions_capture import capture_exception
from posthog.models import Dashboard, DashboardTile, Insight, Team, User
from posthog.sync import database_sync_to_async

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.dashboards.types import (
    DashboardInsightCreationTaskExecutionState,
    DashboardInsightSearchTaskExecutionState,
    PartialDashboardInsightCreationTaskExecutionState,
    PartialDashboardInsightSearchTaskExecutionState,
)
from ee.hogai.graph.insights.nodes import InsightSearchNode
from ee.hogai.graph.task_executor.base import GenericTaskExecutorNode, TaskExecutorTool
from ee.hogai.graph.task_executor.tools import NodeTaskExecutorTool, SubgraphTaskExecutorTool
from ee.hogai.utils.helpers import cast_assistant_query
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import InsightCreationTaskExecutionResult, InsightQuery, InsightSearchTaskExecutionResult

from .prompts import (
    DASHBOARD_CREATION_ERROR_MESSAGE,
    DASHBOARD_NAME_GENERATION_SYSTEM_PROMPT,
    DASHBOARD_NO_INSIGHTS_MESSAGE,
    DASHBOARD_SUCCESS_MESSAGE_TEMPLATE,
    HYPERLINK_USAGE_INSTRUCTIONS,
    QUERIES_WITHOUT_INSIGHTS_MESSAGE_TEMPLATE,
)

logger = structlog.get_logger(__name__)


class QueryMetadata(BaseModel):
    found_insight_ids: set[int]
    created_insight_ids: set[int]
    found_insight_messages: list[str]
    created_insight_messages: list[str]
    query: InsightQuery


class DashboardInsightSearchTaskExecutorNode(
    GenericTaskExecutorNode[
        DashboardInsightSearchTaskExecutionState,
        PartialDashboardInsightSearchTaskExecutionState,
        InsightSearchTaskExecutionResult,
    ]
):
    """
    Task executor node specifically for insight search operations.
    """

    def __init__(self, team: Team, user: User, executor: AssistantNode):
        super().__init__(team, user, executor)

    def _create_task_executor_tool(
        self, executor: Union[CompiledStateGraph, AssistantNode]
    ) -> TaskExecutorTool[InsightSearchTaskExecutionResult]:
        """Create the appropriate task executor tool based on executor type."""
        if isinstance(executor, CompiledStateGraph):
            raise ValueError("SubgraphTaskExecutorTool only works with InsightCreationTaskExecutionResult")
        else:
            return NodeTaskExecutorTool(executor)

    def _get_node_name(self) -> AssistantNodeName:
        """Get the node name for this executor."""
        return AssistantNodeName.DASHBOARD_CREATOR

    def _create_final_response(
        self,
        task_results: list[InsightSearchTaskExecutionResult],
        tool_call_id: str,
        task_execution_message_id: str,
        tasks: list[Any],
    ) -> PartialDashboardInsightSearchTaskExecutionState:
        """Create the final response after task execution."""
        final_completed_message = TaskExecutionMessage(id=task_execution_message_id, tasks=tasks.copy())

        return PartialDashboardInsightSearchTaskExecutionState(
            messages=[
                final_completed_message,
                AssistantToolCallMessage(
                    content=f"Completed {len(task_results)} insight search tasks successfully.",
                    id=str(uuid.uuid4()),
                    tool_call_id=tool_call_id,
                ),
            ],
            task_results=task_results,
            tasks=None,  # Reset tasks
        )

    def _create_empty_response(self, tool_call_id: str) -> PartialDashboardInsightSearchTaskExecutionState:
        """Create an empty response when no tasks are provided."""
        return PartialDashboardInsightSearchTaskExecutionState(
            messages=[AssistantToolCallMessage(content="No tasks to execute", tool_call_id=tool_call_id)]
        )


class DashboardInsightCreationTaskExecutorNode(
    GenericTaskExecutorNode[
        DashboardInsightCreationTaskExecutionState,
        PartialDashboardInsightCreationTaskExecutionState,
        InsightCreationTaskExecutionResult,
    ]
):
    """
    Task executor node specifically for insight creation operations.
    """

    def __init__(self, team: Team, user: User, executor: CompiledStateGraph):
        super().__init__(team, user, executor)

    def _create_task_executor_tool(
        self, executor: Union[CompiledStateGraph, AssistantNode]
    ) -> TaskExecutorTool[InsightCreationTaskExecutionResult]:
        """Create the appropriate task executor tool based on executor type."""
        if isinstance(executor, CompiledStateGraph):
            return SubgraphTaskExecutorTool(executor)
        else:
            raise ValueError("NodeTaskExecutorTool only works with InsightCreationArtifact")

    def _get_node_name(self) -> AssistantNodeName:
        """Get the node name for this executor."""
        return AssistantNodeName.DASHBOARD_CREATOR

    def _create_final_response(
        self,
        task_results: list[InsightCreationTaskExecutionResult],
        tool_call_id: str,
        task_execution_message_id: str,
        tasks: list[Any],
    ) -> PartialDashboardInsightCreationTaskExecutionState:
        """Create the final response after task execution."""
        final_completed_message = TaskExecutionMessage(id=task_execution_message_id, tasks=tasks.copy())

        return PartialDashboardInsightCreationTaskExecutionState(
            messages=[
                final_completed_message,
                AssistantToolCallMessage(
                    content=f"Completed {len(task_results)} insight creation tasks successfully.",
                    id=str(uuid.uuid4()),
                    tool_call_id=tool_call_id,
                ),
            ],
            task_results=task_results,
            tasks=None,  # Reset tasks
        )

    def _create_empty_response(self, tool_call_id: str) -> PartialDashboardInsightCreationTaskExecutionState:
        """Create an empty response when no tasks are provided."""
        return PartialDashboardInsightCreationTaskExecutionState(
            messages=[AssistantToolCallMessage(content="No tasks to execute", tool_call_id=tool_call_id)]
        )


class DashboardCreatorNode(AssistantNode):
    REASONING_MESSAGE = "Creating dashboard"

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
            capture_exception(e)
            logger.exception("Failed to stream reasoning message", error=str(e), content=progress_message)

    def _get_found_insight_count(self, queries_metadata: dict[str, QueryMetadata]) -> int:
        return sum(len(query.found_insight_ids) for query in queries_metadata.values())

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        if not state.create_dashboard_query:
            return self._create_error_response(
                "Dashboard creation query is required", state.root_tool_call_id or "unknown"
            )

        if not state.search_insights_queries:
            return self._create_error_response(
                "Search insights queries are required", state.root_tool_call_id or "unknown"
            )
        try:
            result = {
                str(i): QueryMetadata(
                    query=query,
                    found_insight_ids=set(),
                    created_insight_ids=set(),
                    found_insight_messages=[],
                    created_insight_messages=[],
                )
                for i, query in enumerate(state.search_insights_queries)
            }

            self._stream_reasoning(
                progress_message=f"Searching for {len(state.search_insights_queries)} insights",
                writer=self._get_stream_writer(),
            )

            result = await self._search_insights(result, state, config)

            self._stream_reasoning(
                progress_message=f"Found {self._get_found_insight_count(result)} insights",
                writer=self._get_stream_writer(),
            )

            left_to_create = {
                query_id: result[query_id].query for query_id in result.keys() if not result[query_id].found_insight_ids
            }

            if left_to_create:
                self._stream_reasoning(
                    progress_message=f"Will create {len(left_to_create)} insights", writer=self._get_stream_writer()
                )

                result = await self._create_insights(left_to_create, result, state, config)

            all_insight_ids = set()
            messages = []
            for query_metadata in result.values():
                all_insight_ids.update(query_metadata.created_insight_ids | query_metadata.found_insight_ids)
                messages.extend(query_metadata.found_insight_messages + query_metadata.created_insight_messages)

            if not all_insight_ids:
                return self._create_no_insights_response(state.root_tool_call_id or "unknown", "\n".join(messages))

            dashboard_name = await self._generate_dashboard_name(state.create_dashboard_query, messages)

            dashboard, all_insights = await self._create_dashboard_with_insights(dashboard_name, all_insight_ids)

            queries_no_insights = [
                query_metadata.query.name
                for query_metadata in result.values()
                if not query_metadata.created_insight_ids and not query_metadata.found_insight_ids
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

    def _build_insight_url(self, id: str) -> str:
        """Build the URL for an insight."""
        return f"/project/{self._team.id}/insights/{id}"

    def _build_dashboard_url(self, id: int) -> str:
        """Build the URL for a dashboard."""
        return f"/project/{self._team.id}/dashboard/{id}"

    async def _create_insights(
        self,
        left_to_create: dict[str, InsightQuery],
        query_metadata: dict[str, QueryMetadata],
        state: AssistantState,
        config: RunnableConfig,
    ) -> dict[str, QueryMetadata]:
        from ee.hogai.graph.graph import InsightsAssistantGraph

        compiled_insights_subgraph = InsightsAssistantGraph(self._team, self._user).compile_full_graph()
        executor_node = DashboardInsightCreationTaskExecutorNode(self._team, self._user, compiled_insights_subgraph)
        task_executor_state = DashboardInsightCreationTaskExecutionState(
            messages=state.messages,
            root_tool_call_id=state.root_tool_call_id,
            tasks=[
                TaskExecutionItem(
                    id=query_id,
                    prompt=query_metadata[query_id].query.description,
                    status=TaskExecutionStatus.PENDING,
                    description=f"Creating insight `{query_metadata[query_id].query.name}`",
                    progress_text="Creating insight...",
                )
                for query_id in left_to_create.keys()
            ],
        )

        result = await executor_node.arun(task_executor_state, config)
        final_task_executor_state = PartialDashboardInsightCreationTaskExecutionState.model_validate(result)

        created_insights = await self._save_insights(final_task_executor_state.task_results, query_metadata)

        for task in final_task_executor_state.task_results:
            if task.status == TaskExecutionStatus.COMPLETED:
                query_metadata[task.id].created_insight_ids.update(created_insights[task.id])
                query_metadata[task.id].created_insight_messages.append(
                    f"\n -{query_metadata[task.id].query.name}: Insight was created successfully with the description **{query_metadata[task.id].query.description}**"
                )
            else:
                query_metadata[task.id].created_insight_messages.append(
                    f"\n -{query_metadata[task.id].query.name}: Could not create insights for the query with the description **{task.description}**"
                )

        return query_metadata

    async def _search_insights(
        self,
        queries_metadata: dict[str, QueryMetadata],
        state: AssistantState,
        config: RunnableConfig,
    ) -> dict[str, QueryMetadata]:
        insight_search_node = InsightSearchNode(self._team, self._user)
        executor_node = DashboardInsightSearchTaskExecutorNode(self._team, self._user, insight_search_node)

        tasks = [
            TaskExecutionItem(
                id=query_id,
                prompt=query_metadata.query.description,
                status=TaskExecutionStatus.PENDING,
                description=f"Searching for insight `{query_metadata.query.name}`",
                progress_text="Searching for existing insights...",
            )
            for query_id, query_metadata in queries_metadata.items()
        ]

        task_executor_state = DashboardInsightSearchTaskExecutionState(
            messages=state.messages,
            root_tool_call_id=state.root_tool_call_id,
            tasks=tasks,
        )

        result = await executor_node.arun(task_executor_state, config)
        final_task_executor_state = PartialDashboardInsightSearchTaskExecutionState.model_validate(result)

        for task_result in final_task_executor_state.task_results:
            if task_result.status == TaskExecutionStatus.COMPLETED:
                for artifact in task_result.artifacts:
                    if artifact.insight_ids:
                        queries_metadata[task_result.id].found_insight_ids.update(artifact.insight_ids)
                        queries_metadata[task_result.id].found_insight_messages.append(
                            f"\n -{queries_metadata[task_result.id].query.name}: Found insights for the query and the reason for selection is **{artifact.selection_reason}**"
                        )
                    else:
                        queries_metadata[task_result.id].found_insight_messages.append(
                            f"\n -{queries_metadata[task_result.id].query.name}: Could not find insights for the query with the description **{task_result.description}**"
                        )
        return queries_metadata

    @database_sync_to_async
    def _save_insights(
        self, task_results: list[InsightCreationTaskExecutionResult], query_metadata: dict[str, QueryMetadata]
    ) -> dict[str, set[int]]:
        """Create insights in parallel."""
        from posthog.models import Insight

        created_insights: dict[str, set[int]] = {
            task.id: set() for task in task_results if task.status == TaskExecutionStatus.COMPLETED
        }

        insights_to_create = []
        insight_metadata = []

        for task_result in task_results:
            if task_result.status != TaskExecutionStatus.COMPLETED:
                continue
            for artifact in task_result.artifacts:
                insight_name = query_metadata[task_result.id].query.name[:400]  # Max 400 chars
                insight_description = query_metadata[task_result.id].query.description[:400]  # Max 400 chars

                if isinstance(artifact.query, AssistantHogQLQuery):
                    converted = {"kind": "DataTableNode", "source": cast_assistant_query(artifact.query).model_dump()}
                else:
                    converted = {"kind": "InsightVizNode", "source": cast_assistant_query(artifact.query).model_dump()}

                insight = Insight(
                    name=insight_name,
                    team=self._team,
                    created_by=self._user,
                    query=converted,
                    description=insight_description,
                    saved=True,
                )
                insights_to_create.append(insight)
                insight_metadata.append(task_result.id)

        created_insight_objects = Insight.objects.bulk_create(insights_to_create)

        for insight, task_id in zip(created_insight_objects, insight_metadata):
            created_insights[task_id].add(insight.id)

        return created_insights

    async def _generate_dashboard_name(self, query: str, last_messages: list[str]) -> str:
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
            capture_exception(e)
            logger.exception(f"Error generating dashboard name: {e}", exc_info=True)
            return "Analytics Dashboard"

    async def _create_dashboard_with_insights(
        self, dashboard_name: str, insights: set[int]
    ) -> tuple[Dashboard, list[Insight]]:
        """Create a dashboard and add the insights to it."""
        self._stream_reasoning(progress_message="Saving your dashboard", writer=self._get_stream_writer())

        @database_sync_to_async
        def create_dashboard_sync():
            all_insights: list[Insight] = []
            # Create the dashboard
            dashboard = Dashboard.objects.create(
                name=dashboard_name,
                team=self._team,
                created_by=self._user,
            )

            # Add insights to the dashboard via DashboardTile
            for insight_id in insights:
                insight = Insight.objects.get(id=insight_id, team=self._team)
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
            root_tool_insight_plan=None,
            insight_ids=None,
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
            root_tool_insight_plan=None,
        )

    def _create_error_response(self, content: str, tool_call_id: str) -> PartialAssistantState:
        """Create error response for the assistant."""
        capture_exception(Exception(content))
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
            root_tool_insight_plan=None,
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
