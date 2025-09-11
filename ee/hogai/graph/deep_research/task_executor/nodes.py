import uuid
from typing import Any, Union

import structlog
from langgraph.graph.state import CompiledStateGraph

from posthog.schema import AssistantToolCallMessage, TaskExecutionMessage

from posthog.models import Team, User

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.deep_research.types import (
    DeepResearchNodeName,
    DeepResearchSingleTaskResult,
    DeepResearchState,
    PartialDeepResearchState,
)
from ee.hogai.graph.task_executor.base import GenericTaskExecutorNode, TaskExecutorTool
from ee.hogai.graph.task_executor.prompts import EXECUTE_TASKS_TOOL_RESULT
from ee.hogai.graph.task_executor.tools import SubgraphTaskExecutorTool

logger = structlog.get_logger(__name__)


class DeepResearchTaskExecutorNode(
    GenericTaskExecutorNode[DeepResearchState, PartialDeepResearchState, DeepResearchSingleTaskResult]
):
    """
    Task executor node specifically for deep research workflows.
    """

    def __init__(self, team: Team, user: User, executor: Union[CompiledStateGraph, AssistantNode]):
        super().__init__(team, user, executor)

    def _create_task_executor_tool(
        self, executor: Union[CompiledStateGraph, AssistantNode]
    ) -> TaskExecutorTool[DeepResearchSingleTaskResult]:
        """Create the appropriate task executor tool based on executor type."""
        if isinstance(executor, CompiledStateGraph):
            return SubgraphTaskExecutorTool(executor)
        else:
            raise ValueError("NodeTaskExecutorTool only works with InsightSearchArtifact")

    def _get_node_name(self) -> DeepResearchNodeName:
        """Get the node name for this executor."""
        return DeepResearchNodeName.TASK_EXECUTOR

    def _create_final_response(
        self,
        task_results: list[DeepResearchSingleTaskResult],
        tool_call_id: str,
        task_execution_message_id: str,
        tasks: list[Any],
    ) -> PartialDeepResearchState:
        """Create the final response after deep research task execution."""
        formatted_results = ""
        for single_task_result in task_results:
            artifact_lines = []
            for artifact in single_task_result.artifacts:
                artifact_lines.append(f"- {artifact.id}: {artifact.description}")
            artifacts_str = "\n".join(artifact_lines)
            formatted_results += (
                f"- {single_task_result.description}:\n{single_task_result.result}\nArtifacts:\n{artifacts_str}\n"
            )

        final_completed_message = TaskExecutionMessage(id=task_execution_message_id, tasks=tasks.copy())
        return PartialDeepResearchState(
            messages=[
                final_completed_message,
                AssistantToolCallMessage(
                    content=EXECUTE_TASKS_TOOL_RESULT.format(results=formatted_results),
                    id=str(uuid.uuid4()),
                    tool_call_id=tool_call_id,
                ),
            ],
            task_results=task_results,
            tasks=None,  # we reset this so planner doesn't come here again by mistake
        )

    def _create_empty_response(self, tool_call_id: str) -> PartialDeepResearchState:
        """Create an empty response when no tasks are provided."""
        return PartialDeepResearchState(
            messages=[AssistantToolCallMessage(content="No tasks to execute", tool_call_id=tool_call_id)]
        )
