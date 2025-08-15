from typing import cast
import uuid
import structlog

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer

from ee.hogai.graph.base import BaseAssistantNode
from ee.hogai.graph.deep_research.task_executor.prompts import EXECUTE_TASKS_TOOL_RESULT
from ee.hogai.graph.deep_research.types import (
    DeepResearchNodeName,
    DeepResearchSingleTaskResult,
    DeepResearchState,
    PartialDeepResearchState,
)
from ee.hogai.utils.helpers import find_last_message_of_type
from ee.hogai.utils.types.base import InsightArtifact
from posthog.exceptions_capture import capture_exception
from .tools import ExecuteTasksTool
from posthog.models import Team, User
from posthog.schema import AssistantMessage, AssistantToolCallMessage, TaskExecutionMessage, TaskExecutionStatus


logger = structlog.get_logger(__name__)


class TaskExecutorNode(BaseAssistantNode[DeepResearchState, PartialDeepResearchState]):
    """
    Core task execution node that handles research tasks (Tasks coming from the Deep Research Planner).
    """

    def __init__(self, team: Team, user: User, insights_subgraph):
        super().__init__(team, user)
        self._execute_tasks_tool = ExecuteTasksTool(insights_subgraph)

    async def arun(self, state: DeepResearchState, config: RunnableConfig) -> PartialDeepResearchState | None:
        last_tool_call_message = find_last_message_of_type(state.messages, AssistantMessage)
        if not (last_tool_call_message and last_tool_call_message.tool_calls):
            raise ValueError("No tool call message found")

        tool_call_id = last_tool_call_message.tool_calls[0].id
        if not state.tasks:
            logger.warning("No research step provided to execute")
            return PartialDeepResearchState(
                messages=[AssistantToolCallMessage(content="No tasks to execute", tool_call_id=tool_call_id)]
            )

        return await self._execute_tasks(state, config, tool_call_id)

    async def _execute_tasks(
        self, state: DeepResearchState, config: RunnableConfig, tool_call_id: str
    ) -> PartialDeepResearchState:
        try:
            current_task_index = 0
            writer = get_stream_writer()

            artifacts: list[InsightArtifact] = []
            for task_result in state.task_results:
                artifacts.extend(task_result.artifacts)

            # Create initial TaskExecutionMessage with all tasks as pending
            tasks = state.tasks.copy()
            input_tuples = []
            for task in tasks:
                task.status = TaskExecutionStatus.IN_PROGRESS
                task_artifacts = []
                if task.artifact_ids:
                    task_artifacts = [artifact for artifact in artifacts if artifact.id in task.artifact_ids]
                input_tuples.append((task, task_artifacts))

            # Send initial message showing all tasks as pending
            initial_message = TaskExecutionMessage(id=str(uuid.uuid4()), tasks=tasks)
            writer(self._message_to_langgraph_update(initial_message, DeepResearchNodeName.TASK_EXECUTOR))

            task_results = []
            async for task_result in self._execute_tasks_tool.astream(input_tuples, config):
                task_result = cast(DeepResearchSingleTaskResult, task_result)
                tasks[current_task_index].status = task_result.status
                completed_message = TaskExecutionMessage(id=str(uuid.uuid4()), tasks=tasks.copy())
                if current_task_index < len(tasks) - 2:
                    # We don't need to stream the last message twice
                    writer(self._message_to_langgraph_update(completed_message, DeepResearchNodeName.TASK_EXECUTOR))
                current_task_index += 1
                task_results.append(task_result)

            formatted_results = ""
            for single_task_result in task_results:
                artifact_lines = []
                for artifact in single_task_result.artifacts:
                    artifact_lines.append(f"- {artifact.id}: {artifact.description}")
                artifacts_str = "\n".join(artifact_lines)
                formatted_results += (
                    f"- {single_task_result.description}:\n{single_task_result.result}\nArtifacts:\n{artifacts_str}\n"
                )

            return PartialDeepResearchState(
                messages=[
                    completed_message,
                    AssistantToolCallMessage(
                        content=EXECUTE_TASKS_TOOL_RESULT.format(results=formatted_results),
                        id=str(uuid.uuid4()),
                        tool_call_id=tool_call_id,
                    ),
                ],
                task_results=task_results,
                tasks=None,  # we reset this so that the planner tools router doesn't come here again by mistake
            )

        except Exception as e:
            capture_exception(e)
            raise
