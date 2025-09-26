from typing import Literal, cast
from uuid import uuid4

from django.db import transaction

import structlog
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from posthog.schema import AssistantHogQLQuery, AssistantToolCallMessage, TaskExecutionItem, TaskExecutionStatus

from posthog.exceptions_capture import capture_exception
from posthog.models import Dashboard, DashboardTile, Insight
from posthog.sync import database_sync_to_async

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.parallel_task_execution.mixins import (
    WithInsightCreationTaskExecution,
    WithInsightSearchTaskExecution,
)
from ee.hogai.graph.parallel_task_execution.nodes import BaseTaskExecutorNode, TaskExecutionInputTuple
from ee.hogai.utils.helpers import build_dashboard_url, build_insight_url, cast_assistant_query
from ee.hogai.utils.types import AssistantNodeName, AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import BaseStateWithTasks, InsightArtifact, InsightQuery, TaskResult
from ee.hogai.utils.types.composed import MaxNodeName

from .prompts import (
    DASHBOARD_CREATION_ERROR_MESSAGE,
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


class DashboardCreationExecutorNode(
    BaseTaskExecutorNode[
        BaseStateWithTasks,
        BaseStateWithTasks,
    ],
    WithInsightSearchTaskExecution,
    WithInsightCreationTaskExecution,
):
    """
    Task executor node specifically for insight search operations.
    """

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.DASHBOARD_CREATION_EXECUTOR

    async def _aget_input_tuples(self, state: BaseStateWithTasks) -> list[TaskExecutionInputTuple]:
        if not state.tasks:
            raise ValueError("No tasks to execute")
        input_tuples: list[TaskExecutionInputTuple] = []
        for task in state.tasks:
            if task.task_type == "search_insights":
                input_tuples.append((task, [], self._execute_search_insights))
            elif task.task_type == "create_insight":
                input_tuples.append((task, [], self._execute_create_insight))
            else:
                raise ValueError(f"Unsupported task type: {task.task_type}")
        return input_tuples


class DashboardCreationNode(AssistantNode):
    REASONING_MESSAGE = "Creating dashboard"

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.DASHBOARD_CREATION

    def _get_found_insight_count(self, queries_metadata: dict[str, QueryMetadata]) -> int:
        return sum(len(query.found_insight_ids) for query in queries_metadata.values())

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        dashboard_name = (
            state.dashboard_name[:50] if state.dashboard_name else "Analytics Dashboard"
        )  # Default dashboard name here to avoid not fulfilling the request

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

            await self._write_reasoning(content=f"Searching for {len(state.search_insights_queries)} insights")

            result = await self._search_insights(result, config)

            await self._write_reasoning(content=f"Found {self._get_found_insight_count(result)} insights")

            left_to_create = {
                query_id: result[query_id].query for query_id in result.keys() if not result[query_id].found_insight_ids
            }

            if left_to_create:
                await self._write_reasoning(content=f"Will create {len(left_to_create)} insights")

                result = await self._create_insights(left_to_create, result, config)

            all_insight_ids = set()
            messages = []
            for query_metadata in result.values():
                all_insight_ids.update(query_metadata.created_insight_ids | query_metadata.found_insight_ids)
                messages.extend(query_metadata.found_insight_messages + query_metadata.created_insight_messages)

            if not all_insight_ids:
                return self._create_no_insights_response(state.root_tool_call_id or "unknown", "\n".join(messages))

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
                f"Error in DashboardCreationNode: {e}",
                extra={
                    "team_id": getattr(self._team, "id", "unknown"),
                    "error": str(e),
                },
                exc_info=True,
            )
            return self._create_error_response(DASHBOARD_CREATION_ERROR_MESSAGE, state.root_tool_call_id or "unknown")

    async def _create_insights(
        self,
        left_to_create: dict[str, InsightQuery],
        query_metadata: dict[str, QueryMetadata],
        config: RunnableConfig,
    ) -> dict[str, QueryMetadata]:
        task_executor_state = BaseStateWithTasks(
            tasks=[
                TaskExecutionItem(
                    id=query_id,
                    prompt=query_metadata[query_id].query.description,
                    status=TaskExecutionStatus.PENDING,
                    description=f"Creating insight `{query_metadata[query_id].query.name}`",
                    progress_text="Creating insight...",
                    task_type="create_insight",
                )
                for query_id in left_to_create.keys()
            ],
        )

        executor = DashboardCreationExecutorNode(self._team, self._user)
        result = await executor.arun(task_executor_state, config)

        query_metadata = await self._process_insight_creation_results(result.task_results, query_metadata)

        return query_metadata

    async def _search_insights(
        self,
        queries_metadata: dict[str, QueryMetadata],
        config: RunnableConfig,
    ) -> dict[str, QueryMetadata]:
        tasks = [
            TaskExecutionItem(
                id=query_id,
                prompt=query_metadata.query.description,
                status=TaskExecutionStatus.PENDING,
                description=f"Searching for insight `{query_metadata.query.name}`",
                progress_text="Searching for existing insights...",
                task_type="search_insights",
            )
            for query_id, query_metadata in queries_metadata.items()
        ]

        task_executor_state = BaseStateWithTasks(
            tasks=tasks,
        )

        executor = DashboardCreationExecutorNode(self._team, self._user)
        result = await executor.arun(task_executor_state, config)
        final_task_executor_state = BaseStateWithTasks.model_validate(result)

        for task_result in final_task_executor_state.task_results:
            if task_result.status == TaskExecutionStatus.COMPLETED:
                for artifact in task_result.artifacts:
                    if artifact.id:
                        queries_metadata[task_result.id].found_insight_ids.add(cast(int, artifact.id))
                        queries_metadata[task_result.id].found_insight_messages.append(
                            f"\n -{queries_metadata[task_result.id].query.name}: Found insights for the query and the reason for selection is **{artifact.content}**"
                        )
                    else:
                        queries_metadata[task_result.id].found_insight_messages.append(
                            f"\n -{queries_metadata[task_result.id].query.name}: Could not find insights for the query with the description **{task_result.description}**"
                        )
        return queries_metadata

    @transaction.atomic
    def _save_insights(self, insights_to_create: list[Insight]) -> list[Insight]:
        return Insight.objects.bulk_create(insights_to_create)

    @database_sync_to_async
    def _process_insight_creation_results(
        self, task_results: list[TaskResult], query_metadata: dict[str, QueryMetadata]
    ) -> dict[str, QueryMetadata]:
        insights_to_create = []
        insight_metadata = []

        for task_result in task_results:
            if task_result.status != TaskExecutionStatus.COMPLETED:
                query_metadata[task_result.id].created_insight_messages.append(
                    f"\n -{query_metadata[task_result.id].query.name}: Could not create insights for the query with the description **{task_result.result}**"
                )
                continue

            for artifact in task_result.artifacts:
                if not isinstance(artifact, InsightArtifact):
                    continue
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

        created_insight_objects = self._save_insights(insights_to_create)

        for insight, task_id in zip(created_insight_objects, insight_metadata):
            query_metadata[task_id].created_insight_ids.add(insight.id)
            query_metadata[task_id].created_insight_messages.append(
                f"\n -{query_metadata[task_id].query.name}: Insight was created successfully with the description **{query_metadata[task_id].query.description}**"
            )

        return query_metadata

    async def _create_dashboard_with_insights(
        self, dashboard_name: str, insights: set[int]
    ) -> tuple[Dashboard, list[Insight]]:
        """Create a dashboard and add the insights to it."""
        await self._write_reasoning(content="Saving your dashboard")

        @database_sync_to_async
        @transaction.atomic
        def create_dashboard_sync():
            all_insights: list[Insight] = []
            # Create the dashboard
            dashboard = Dashboard.objects.create(
                name=dashboard_name,
                team=self._team,
                created_by=self._user,
            )

            # Add insights to the dashboard via DashboardTile
            all_insights = list(Insight.objects.filter(id__in=insights, team=self._team))

            tiles_to_create = [
                DashboardTile(
                    dashboard=dashboard,
                    insight_id=insight_id,
                    layouts={},  # Default layout
                )
                for insight_id in insights
            ]
            DashboardTile.objects.bulk_create(tiles_to_create)

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
            [f"[{insight.name}]({build_insight_url(self._team, insight.short_id)})" for insight in insights]
        )

        success_message = DASHBOARD_SUCCESS_MESSAGE_TEMPLATE.format(
            dashboard_name=dashboard.name,
            insight_count=insight_count,
            insight_plural=insight_plural,
            insights_list=insights_list,
            dashboard_url=build_dashboard_url(self._team, dashboard.id),
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
            dashboard_name=None,
            search_insights_queries=None,
            root_tool_call_id=None,
            root_tool_insight_plan=None,
            selected_insight_ids=None,
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
            dashboard_name=None,
            root_tool_call_id=None,
            search_insights_queries=None,
            selected_insight_ids=None,
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
            dashboard_name=None,
            root_tool_call_id=None,
            search_insights_queries=None,
            selected_insight_ids=None,
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
