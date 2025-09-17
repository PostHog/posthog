import uuid
from collections.abc import Sequence
from typing import cast

import structlog
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from posthog.schema import (
    AssistantMessage,
    AssistantToolCallMessage,
    HumanMessage,
    TaskExecutionItem,
    TaskExecutionMessage,
    TaskExecutionStatus,
    VisualizationMessage,
)

from posthog.exceptions_capture import capture_exception

from ee.hogai.graph.deep_research.task_executor.prompts import AGENT_TASK_PROMPT_TEMPLATE, EXECUTE_TASKS_TOOL_RESULT
from ee.hogai.graph.deep_research.types import DeepResearchNodeName, DeepResearchState, PartialDeepResearchState
from ee.hogai.graph.graph import InsightsAssistantGraph
from ee.hogai.graph.parallel_task_execution.nodes import BaseTaskExecutorNode, TaskExecutionInputTuple
from ee.hogai.utils.helpers import extract_stream_update, find_last_message_of_type
from ee.hogai.utils.state import is_task_started_update, is_value_update
from ee.hogai.utils.types.base import (
    AnyAssistantGeneratedQuery,
    AssistantMessageUnion,
    AssistantState,
    InsightArtifact,
    TaskResult,
)
from ee.hogai.utils.types.composed import MaxNodeName

logger = structlog.get_logger(__name__)


class DeepResearchTaskExecutorNode(BaseTaskExecutorNode[DeepResearchState, PartialDeepResearchState]):
    """
    Core task execution node that handles parallel task execution
    """

    tool_call_id: str

    @property
    def node_name(self) -> MaxNodeName:
        return DeepResearchNodeName.TASK_EXECUTOR

    async def arun(self, state: DeepResearchState, config: RunnableConfig) -> PartialDeepResearchState:
        last_tool_call_message = find_last_message_of_type(state.messages, AssistantMessage)
        if not (last_tool_call_message and last_tool_call_message.tool_calls):
            raise ValueError("No tool call message found")

        tool_call_id = last_tool_call_message.tool_calls[0].id
        self.tool_call_id = tool_call_id
        if not state.tasks:
            logger.warning("No research step provided to execute")
            return PartialDeepResearchState(
                messages=[AssistantToolCallMessage(content="No tasks to execute", tool_call_id=tool_call_id)]
            )

        return await self._arun(state, config)

    async def _aget_input_tuples(self, state: DeepResearchState) -> list[TaskExecutionInputTuple]:
        tasks = state.tasks
        if not tasks:
            raise ValueError("No tasks to execute")
        input_tuples: list[TaskExecutionInputTuple] = []
        for task in tasks:
            if task.task_type == "create_insight":
                input_tuples.append((task, [], self._execute_task_with_insights))
            else:
                raise ValueError(f"Unsupported task type: {task.task_type}")
        return input_tuples

    async def _aget_final_state(
        self, tasks: list[TaskExecutionItem], task_results: list[TaskResult]
    ) -> PartialDeepResearchState:
        formatted_results = ""
        for single_task_result in task_results:
            artifact_lines = []
            for artifact in single_task_result.artifacts:
                artifact_lines.append(f"- {artifact.id}: {artifact.description}")
            artifacts_str = "\n".join(artifact_lines)
            formatted_results += (
                f"- {single_task_result.description}:\n{single_task_result.result}\nArtifacts:\n{artifacts_str}\n"
            )

        final_completed_message = TaskExecutionMessage(id=self._task_execution_message_id, tasks=tasks.copy())
        return PartialDeepResearchState(
            messages=[
                final_completed_message,
                AssistantToolCallMessage(
                    content=EXECUTE_TASKS_TOOL_RESULT.format(results=formatted_results),
                    id=str(uuid.uuid4()),
                    tool_call_id=self.tool_call_id,
                ),
            ],
            task_results=task_results,
            tasks=None,  # we reset this so that the planner tools router doesn't come here again by mistake
        )

    async def _execute_task_with_insights(self, input_dict: dict) -> TaskResult | None:
        """Execute a single task using the full insights pipeline.

        Always returns a TaskResult (even for failures), never None.
        The type allows None for compatibility with the base class.
        """

        task = input_dict["task"]
        artifacts = input_dict["artifacts"]
        config = input_dict.get("config")

        self._current_task_id = task.id

        # This is needed by the InsightsAssistantGraph to return an AssistantToolCallMessage
        task_tool_call_id = f"task_{uuid.uuid4().hex[:8]}"

        formatted_instructions = AGENT_TASK_PROMPT_TEMPLATE.format(
            task_prompt=task.prompt, task_description=task.description
        )

        human_message = HumanMessage(content=formatted_instructions, id=str(uuid.uuid4()))
        input_state = AssistantState(
            messages=[human_message],
            start_id=human_message.id,
            root_tool_call_id=task_tool_call_id,
            root_tool_insight_plan=task.prompt,
        )

        subgraph_result_messages: list[AssistantMessageUnion] = []
        assistant_graph = InsightsAssistantGraph(self._team, self._user).compile_full_graph()
        try:
            async for chunk in assistant_graph.astream(
                input_state,
                config,
                subgraphs=True,
                stream_mode=["updates", "debug"],
            ):
                if not chunk:
                    continue

                update = extract_stream_update(chunk)
                if is_value_update(update):
                    _, content = update
                    node_name = next(iter(content.keys()))
                    messages = content[node_name]["messages"]
                    subgraph_result_messages.extend(messages)
                elif is_task_started_update(update):
                    _, task_update = update
                    node_name = task_update["payload"]["name"]  # type: ignore
                    node_input = task_update["payload"]["input"]  # type: ignore
                    reasoning_message = await assistant_graph.aget_reasoning_message_by_node_name[node_name](
                        node_input, ""
                    )
                    if reasoning_message:
                        progress_text = reasoning_message.content
                        if reasoning_message.substeps:
                            progress_text = reasoning_message.substeps[-1]
                        await self._reasoning_callback(task.id, progress_text)

        except Exception as e:
            capture_exception(e)
            raise

        if len(subgraph_result_messages) == 0 or not subgraph_result_messages[-1]:
            logger.warning("Task failed: no messages received from insights subgraph", task_id=task.id)
            return await self._failed_result(task)

        last_message = subgraph_result_messages[-1]

        if not isinstance(last_message, AssistantToolCallMessage):
            logger.warning(
                "Task failed: last message is not AssistantToolCallMessage",
                task_id=task.id,
            )
            return await self._failed_result(task)

        response = last_message.content

        artifacts = self._extract_artifacts(subgraph_result_messages, task)
        if len(artifacts) == 0:
            response += "\n\nNo artifacts were generated."
            logger.warning("Task failed: no artifacts extracted", task_id=task.id)
            return await self._failed_result(task)

        await self._reasoning_callback(task.id, None)

        return TaskResult(
            id=task.id,
            description=task.description,
            result=response,
            artifacts=artifacts,
            status=TaskExecutionStatus.COMPLETED,
        )

    async def _failed_result(self, task: TaskExecutionItem) -> TaskResult:
        await self._reasoning_callback(task.id, None)
        return TaskResult(
            id=task.id, description=task.description, result="", artifacts=[], status=TaskExecutionStatus.FAILED
        )

    def _extract_artifacts(
        self, subgraph_result_messages: list[AssistantMessageUnion], task: TaskExecutionItem
    ) -> Sequence[InsightArtifact]:
        """Extract artifacts from insights subgraph execution results."""

        artifacts: list[InsightArtifact] = []
        for message in subgraph_result_messages:
            if isinstance(message, VisualizationMessage) and message.id:
                artifact = InsightArtifact(
                    id=task.id,
                    description=task.prompt,
                    query=cast(AnyAssistantGeneratedQuery, message.answer),
                )
                artifacts.append(artifact)
        return artifacts

    def _get_model(self) -> ChatOpenAI:
        return ChatOpenAI(
            model="gpt-4.1",
            temperature=0.3,
        )
