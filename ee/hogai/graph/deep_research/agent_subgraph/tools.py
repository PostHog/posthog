import uuid

import structlog
from langchain_core.runnables import RunnableLambda, RunnableConfig
from pydantic import BaseModel, Field

from ee.hogai.tool import MaxTool
from ee.hogai.utils.types import (
    AssistantState,
    TaskDefinition,
    TaskResult,
    ArtifactResult,
    ReasoningMessage,
    VisualizationMessage,
    HumanMessage,
)
from posthog.models import Team, User
from posthog.schema import AssistantToolCallMessage
from .prompts import AGENT_TASK_PROMPT_TEMPLATE

logger = structlog.get_logger(__name__)


class ExecuteTasksArgs(BaseModel):
    """Arguments for executing multiple tasks in parallel."""

    tasks: list[TaskDefinition] = Field(description="List of tasks to execute in parallel")


class ExecuteTasksTool(MaxTool):
    """Tool for executing multiple tasks in parallel using the insights subgraph."""

    name: str = "execute_tasks"
    description: str = """
    Execute multiple research tasks in parallel using the full insights pipeline.
    Each task will be executed independently using query planning and appropriate insight generation.
    Tasks can reference artifacts created by other tasks using artifact_short_ids.
    Supports trends, funnels, retention, and SQL query generation based on task content.
    """
    args_schema: type[BaseModel] = ExecuteTasksArgs
    thinking_message: str = "I'm executing multiple research tasks in parallel to provide comprehensive analysis..."

    def __init__(self, team: Team, user: User, insights_subgraph):
        super().__init__(team=team, user=user)
        self._team = team
        self._user = user
        self._insights_subgraph = insights_subgraph

    async def arun(
        self,
        tasks: list[TaskDefinition],
        config: RunnableConfig,
    ):
        """
        Execute tasks in parallel using insights subgraph and yield results as they complete.
        """

        task_executor = RunnableLambda(self._execute_task_with_insights).with_config(run_name="TaskExecutor")

        batch_inputs = [{"task": task, "index": i, "config": config} for i, task in enumerate(tasks)]

        async for task_index, output in task_executor.abatch_as_completed(batch_inputs, config=config):
            task = output["task"]
            result = output["result"]

            result_content = self._extract_result_content(result)
            artifacts = self._extract_artifacts(result, task_index)

            yield TaskResult(description=task.description, result=result_content, artifacts=artifacts)

    async def _execute_task_with_insights(self, input_dict: dict) -> dict:
        """Execute a single task using the full insights pipeline."""

        task = input_dict["task"]
        task_index = input_dict["index"]
        config = input_dict.get("config")

        formatted_instructions = AGENT_TASK_PROMPT_TEMPLATE.format(
            task_prompt=task.description, task_instructions=task.instructions
        )
        human_message = HumanMessage(content=formatted_instructions, id=str(uuid.uuid4()))
        task_tool_call_id = f"task_{task_index}_{uuid.uuid4().hex[:8]}"

        input_state = AssistantState(
            messages=[human_message],
            start_id=human_message.id,
            root_tool_call_id=task_tool_call_id,
            root_tool_insight_plan=task.instructions,
        )

        try:
            raw_result = await self._insights_subgraph.ainvoke(input_state, config)

            result = AssistantState(
                messages=raw_result["messages"],
                start_id=raw_result.get("start_id", human_message.id),
                root_tool_call_id=raw_result.get("root_tool_call_id", task_tool_call_id),
            )
        except Exception as e:
            # Handle cases where the insights subgraph has validation errors or asks for clarification
            raise Exception(f"Error executing task {task_index}: {str(e)}")

        # Check if we need to ask for clarification
        if hasattr(result, "messages") and self._is_clarification_request(result.messages):
            pass

        return {"task": task, "task_index": task_index, "result": result}

    def _extract_result_content(self, subgraph_result) -> str:
        """Extract markdown result content from insights subgraph execution."""

        messages = subgraph_result.messages
        result_parts = [
            message.content
            for message in messages
            if hasattr(message, "content")
            and message.content
            and not isinstance(message, HumanMessage | ReasoningMessage | VisualizationMessage)
        ]

        return (
            "\n\n".join(result_parts)
            if result_parts
            else "Task completed successfully but no detailed results were generated."
        )

    def _extract_artifacts(self, subgraph_result, task_index: int) -> list[ArtifactResult]:
        """Extract artifacts from insights subgraph execution results."""

        artifacts = []
        messages = subgraph_result.messages

        for message in messages:
            if isinstance(message, VisualizationMessage) and message.id:
                artifact = ArtifactResult(
                    short_id=f"viz_{task_index}_{message.id[:8]}",
                    description=f"Visualization from task {task_index + 1}",
                    artifact_type="VisualizationMessage",
                    # Dumping VisualizationMessage object
                    data={"visualization_message": message},
                )
                artifacts.append(artifact)
        return artifacts

    def _is_clarification_request(self, result_messages: list) -> bool:
        """Check if the result messages contain a clarification request."""
        if not result_messages:
            return False

        assistant_tool_call_messages = [msg for msg in result_messages if isinstance(msg, AssistantToolCallMessage)]

        for msg in assistant_tool_call_messages:
            if hasattr(msg, "content") and msg.content and "The agent has requested help from the user" in msg.content:
                return True
        return False
