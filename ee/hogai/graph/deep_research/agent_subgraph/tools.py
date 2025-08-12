import asyncio
import uuid
from typing import Optional

import structlog
from pydantic import BaseModel, Field
from langchain_core.runnables import RunnableConfig

from ee.hogai.tool import MaxTool
from ee.hogai.utils.types import (
    TaskDefinition,
    TaskResult,
    ArtifactResult,
    ReasoningMessage,
    VisualizationMessage,
)
from posthog.models import Team, User
from posthog.schema import AssistantToolCallMessage

logger = structlog.get_logger(__name__)


class ExecuteTasksArgs(BaseModel):
    """Arguments for executing multiple tasks in parallel."""

    tasks: list[TaskDefinition] = Field(description="List of tasks to execute in parallel")


class ArtifactStore:
    """Simple in-memory artifact store for task references."""

    def __init__(self):
        self._artifacts: dict[str, ArtifactResult] = {}

    def store_artifact(self, artifact: ArtifactResult) -> None:
        """Store an artifact by its short_id."""
        self._artifacts[artifact.short_id] = artifact

    def get_artifact(self, short_id: str) -> Optional[ArtifactResult]:
        """Retrieve an artifact by its short_id."""
        return self._artifacts.get(short_id)

    def get_artifacts(self, short_ids: list[str]) -> list[ArtifactResult]:
        """Retrieve multiple artifacts by their short_ids."""
        return [self._artifacts[short_id] for short_id in short_ids if short_id in self._artifacts]


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
        self._artifact_store = ArtifactStore()
        self._insights_subgraph = insights_subgraph

    async def arun(
        self,
        tasks: list[TaskDefinition],
        config: RunnableConfig,
    ):
        """
        Execute tasks in parallel using insights subgraph and yield results as they complete.
        """
        from langchain_core.runnables import RunnableLambda
        import time

        batch_start_time = time.time()

        logger.info(
            "BATCH EXECUTION STARTED",
            total_tasks=len(tasks),
        )

        # Create a runnable from the async function
        task_executor = RunnableLambda(self._execute_task_with_insights).with_config(run_name="TaskExecutor")

        # Prepare inputs for batch processing
        batch_inputs = [{"task": task, "index": i, "config": config} for i, task in enumerate(tasks)]

        # Use abatch_as_completed to process tasks as they complete
        async for task_index, output in task_executor.abatch_as_completed(batch_inputs, config=config):
            task = output["task"]
            result = output["result"]

            processing_start_time = time.time()
            logger.info(
                "PROCESSING TASK RESULT (from tools.py)",
                task_index=task_index,
                task_description=task.description,
                result_available=bool(result),
            )

            # Process the result and check for clarification requests
            result_content = self._extract_result_content(result)
            artifacts = self._extract_artifacts(result, task_index)

            processing_end_time = time.time()
            processing_duration = processing_end_time - processing_start_time

            logger.info(
                "TASK RESULT READY",
                task_index=task_index,
                task_description=task.description,
                result_content_length=len(result_content),
                artifacts_created=len(artifacts),
                processing_time_ms=round(processing_duration * 1000, 2),
                total_time_since_batch_start_seconds=round(processing_end_time - batch_start_time, 2),
            )

            # Yield the task result as it completes
            yield TaskResult(description=task.description, result=result_content, artifacts=artifacts)

    async def _execute_task_with_insights(self, input_dict: dict) -> dict:
        """Execute a single task using the full insights pipeline."""
        from ee.hogai.utils.types import AssistantState
        from posthog.schema import HumanMessage
        import time

        task = input_dict["task"]
        task_index = input_dict["index"]
        config = input_dict.get("config")

        task_start_time = time.time()
        logger.info(
            "TASK EXECUTION STARTED",
            task_index=task_index,
            task_description=task.description,
            instructions_length=len(task.instructions) if task.instructions else 0,
        )

        # Add artificial delay for testing parallel execution
        # TODO: Re-enable this for testing
        if "Create pageviews trends chart" in task.description:
            delay_seconds = 5
            delay_start_time = time.time()
            logger.info(
                "ARTIFICIAL DELAY APPLIED",
                task_index=task_index,
                task_description=task.description,
                delay_seconds=delay_seconds,
                reason="testing_parallel_execution",
            )
            await asyncio.sleep(delay_seconds)
            delay_end_time = time.time()
            actual_delay = delay_end_time - delay_start_time
            logger.info(
                "ARTIFICIAL DELAY COMPLETED",
                task_index=task_index,
                task_description=task.description,
                actual_delay_seconds=round(actual_delay, 2),
            )

        # Create input state for insights subgraph with single task prompt
        # Use just the individual task instructions, not the entire DEEP_RESEARCH command
        human_message = HumanMessage(content=task.instructions, id=str(uuid.uuid4()))
        task_tool_call_id = f"task_{task_index}_{uuid.uuid4().hex[:8]}"

        input_state = AssistantState(
            messages=[human_message],
            start_id=human_message.id,
            root_tool_call_id=task_tool_call_id,
            root_tool_insight_plan=task.instructions,
        )

        try:
            raw_result = await self._insights_subgraph.ainvoke(input_state, config)

            if hasattr(raw_result, "messages"):
                # Already an AssistantState-like object
                result = raw_result
            else:
                # Convert dict result to AssistantState
                result = AssistantState(
                    messages=raw_result["messages"],
                    start_id=raw_result.get("start_id", human_message.id),
                    root_tool_call_id=raw_result.get("root_tool_call_id", task_tool_call_id),
                )
        except Exception as e:
            # Handle cases where the insights subgraph has validation errors or asks for clarification
            logger.warning(
                "INSIGHTS_SUBGRAPH_ERROR",
                task_index=task_index,
                task_description=task.description,
                error_type=type(e).__name__,
                error_message=str(e),
            )
            raise Exception(f"Error executing task {task_index}: {str(e)}")

        task_end_time = time.time()
        task_duration = task_end_time - task_start_time

        # Check if we need to ask for clarification
        if hasattr(result, "messages") and self._is_clarification_request(result.messages):
            logger.warning(
                "CLARIFICATION_REQUEST_DETECTED",
                task_index=task_index,
                task_description=task.description,
                result_preview=result.messages[-1].content[:200] + "..."
                if hasattr(result.messages[-1], "content") and len(result.messages[-1].content) > 200
                else getattr(result.messages[-1], "content", "No content"),
            )

        logger.info(
            "TASK EXECUTION COMPLETED",
            task_index=task_index,
            task_description=task.description,
            execution_time_seconds=round(task_duration, 2),
            had_artificial_delay="Create pageviews trends chart" in task.description,
            output_available=bool(result),
        )

        return {"task": task, "task_index": task_index, "result": result}

    def _extract_result_content(self, subgraph_result) -> str:
        """Extract markdown result content from insights subgraph execution."""
        from posthog.schema import HumanMessage

        # Check if we have stored original messages (which include VisualizationMessages)
        # We want to use the filtered messages for content extraction
        if hasattr(subgraph_result, "messages"):
            messages = subgraph_result.messages
        elif isinstance(subgraph_result, dict):
            messages = subgraph_result.get("messages", [])
        else:
            messages = []

        result_parts = []
        for message in messages:
            # Skip HumanMessage (the initial query) to avoid duplication
            if isinstance(message, HumanMessage):
                continue
            # Handle different message types from insights pipeline
            if isinstance(message, ReasoningMessage):
                # Skip reasoning messages in the final result
                continue
            elif isinstance(message, VisualizationMessage):
                # Skip VisualizationMessage here as they're handled separately as artifacts
                continue
            elif hasattr(message, "content") and message.content:
                # AssistantMessage and other content-based messages
                result_parts.append(message.content)

        if result_parts:
            return "\n\n".join(result_parts)
        else:
            return "Task completed successfully but no detailed results were generated."

    def _extract_artifacts(self, subgraph_result, task_index: int) -> list[ArtifactResult]:
        """Extract artifacts from insights subgraph execution results."""

        artifacts = []

        # Handle AssistantState result from InsightsAssistantGraph
        # Use original messages if available (contains VisualizationMessage), otherwise filtered messages
        if hasattr(subgraph_result, "_original_messages"):
            messages = subgraph_result._original_messages
        elif hasattr(subgraph_result, "messages"):
            messages = subgraph_result.messages
        elif isinstance(subgraph_result, dict):
            messages = subgraph_result.get("messages", [])
        else:
            messages = []

        # Look for visualization messages which can become artifacts
        for message in messages:
            if isinstance(message, VisualizationMessage) and message.id:
                artifact = ArtifactResult(
                    short_id=f"viz_{task_index}_{message.id[:8]}",
                    description=f"Visualization from task {task_index + 1}",
                    artifact_type="VisualizationMessage",
                    data={
                        "visualization_message": message  # Store the actual VisualizationMessage object
                    },
                )
                artifacts.append(artifact)
        return artifacts

    def _is_clarification_request(self, result_messages: list) -> bool:
        """Check if the result messages contain a clarification request."""
        if not result_messages:
            return False

        # Filter to just get AssistantToolCallMessage
        assistant_tool_call_messages = [msg for msg in result_messages if isinstance(msg, AssistantToolCallMessage)]

        # Check for clarification request patterns
        for msg in assistant_tool_call_messages:
            if hasattr(msg, "content") and msg.content and "The agent has requested help from the user" in msg.content:
                return True
        return False
