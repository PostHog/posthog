import uuid

import structlog
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, AssistantToolCall, AssistantToolCallMessage

from ee.hogai.graph.deep_research.task_executor.prompts import EXECUTE_TASKS_TOOL_RESULT
from ee.hogai.graph.deep_research.types import DeepResearchNodeName, DeepResearchState, PartialDeepResearchState
from ee.hogai.graph.parallel_task_execution.mixins import WithInsightCreationTaskExecution
from ee.hogai.graph.parallel_task_execution.nodes import BaseTaskExecutorNode, TaskExecutionInputTuple
from ee.hogai.utils.helpers import find_last_message_of_type
from ee.hogai.utils.types.base import TaskResult
from ee.hogai.utils.types.composed import MaxNodeName

logger = structlog.get_logger(__name__)


class DeepResearchTaskExecutorNode(
    BaseTaskExecutorNode[DeepResearchState, PartialDeepResearchState], WithInsightCreationTaskExecution
):
    """
    Core task execution node that handles parallel task execution
    """

    @property
    def node_name(self) -> MaxNodeName:
        return DeepResearchNodeName.TASK_EXECUTOR

    tool_call_id: str

    async def arun(self, state: DeepResearchState, config: RunnableConfig) -> PartialDeepResearchState:
        last_tool_call_message = find_last_message_of_type(state.messages, AssistantMessage)
        if not (last_tool_call_message and last_tool_call_message.tool_calls):
            raise ValueError("No tool call message found")

        tool_call_id = last_tool_call_message.tool_calls[0].id
        self.tool_call_id = tool_call_id
        return await super().arun(state, config)

    async def _aget_input_tuples(self, tool_calls: list[AssistantToolCall]) -> list[TaskExecutionInputTuple]:
        input_tuples: list[TaskExecutionInputTuple] = []
        for task in tool_calls:
            if task.name == "create_insight":
                input_tuples.append((task, [], self._execute_create_insight))
            else:
                raise ValueError(f"Unsupported task type: {task.name}")
        return input_tuples

    async def _aget_final_state(self, task_results: list[TaskResult]) -> PartialDeepResearchState:
        formatted_results = ""
        for single_task_result in task_results:
            artifact_lines = []
            for artifact in single_task_result.artifacts:
                artifact_lines.append(f"- {artifact.task_id}: {artifact.content}")
            artifacts_str = "\n".join(artifact_lines)
            formatted_results += f"- {single_task_result.result}\nArtifacts:\n{artifacts_str}\n"

        return PartialDeepResearchState(
            messages=[
                AssistantToolCallMessage(
                    content=EXECUTE_TASKS_TOOL_RESULT.format(results=formatted_results),
                    id=str(uuid.uuid4()),
                    tool_call_id=self.tool_call_id,
                ),
            ],
            task_results=task_results,
        )
