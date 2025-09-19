import uuid
from collections.abc import Callable, Coroutine, Sequence
from typing import Any, cast

import structlog
from langchain_openai import ChatOpenAI

from posthog.schema import (
    AssistantToolCallMessage,
    HumanMessage,
    TaskExecutionItem,
    TaskExecutionStatus,
    VisualizationMessage,
)

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.models.user import User

from ee.hogai.graph.parallel_task_execution.prompts import AGENT_TASK_PROMPT_TEMPLATE
from ee.hogai.utils.helpers import extract_stream_update
from ee.hogai.utils.state import is_task_started_update, is_value_update
from ee.hogai.utils.types.base import (
    AnyAssistantGeneratedQuery,
    AssistantMessageUnion,
    AssistantState,
    InsightArtifact,
    TaskResult,
)

logger = structlog.get_logger(__name__)


class WithInsightCreationTaskExecution:
    _team: Team
    _user: User
    _reasoning_callback: Callable[[str, str | None], Coroutine[Any, Any, None]]
    _failed_result: Callable[[TaskExecutionItem], Coroutine[Any, Any, TaskResult]]

    async def _execute_create_insight(self, input_dict: dict) -> TaskResult | None:
        """Execute a single task using the full insights pipeline.

        Always returns a TaskResult (even for failures), never None.
        The type allows None for compatibility with the base class.
        """
        # Import here to avoid circular dependency
        from ee.hogai.graph.graph import InsightsAssistantGraph

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

    def _extract_artifacts(
        self, subgraph_result_messages: list[AssistantMessageUnion], task: TaskExecutionItem
    ) -> Sequence[InsightArtifact]:
        """Extract artifacts from insights subgraph execution results."""

        artifacts: list[InsightArtifact] = []
        for message in subgraph_result_messages:
            if isinstance(message, VisualizationMessage) and message.id:
                artifact = InsightArtifact(
                    task_id=task.id,
                    id=None,  # The InsightsAssistantGraph does not create the insight objects
                    content=task.prompt,
                    query=cast(AnyAssistantGeneratedQuery, message.answer),
                )
                artifacts.append(artifact)
        return artifacts

    def _get_model(self) -> ChatOpenAI:
        return ChatOpenAI(
            model="gpt-4.1",
            temperature=0.3,
        )
