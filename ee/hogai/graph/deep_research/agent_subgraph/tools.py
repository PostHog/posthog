import asyncio
import uuid
from typing import Any, Optional

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
    """Tool for executing multiple tasks in parallel using subagents."""

    name: str = "execute_tasks"
    description: str = """
    Execute multiple research tasks in parallel using different subagents.
    Each task will be executed independently and results will be aggregated.
    Tasks can reference artifacts created by other tasks using artifact_short_ids.
    """
    args_schema: type[BaseModel] = ExecuteTasksArgs
    thinking_message: str = "I'm executing multiple research tasks in parallel to provide comprehensive analysis..."

    def __init__(self, team: Team, user: User):
        super().__init__(team=team, user=user)
        self._team = team
        self._user = user
        self._artifact_store = ArtifactStore()

    async def arun(
        self,
        tasks: list[TaskDefinition],
        run_manager: Optional[Any] = None,
    ):
        """
        Execute tasks in parallel and yield results as they complete, streaming the results.
        """
        from ee.hogai.graph import TrendsGeneratorNode
        from ee.hogai.utils.types import AssistantState
        from posthog.schema import HumanMessage
        from langchain_core.runnables import RunnableLambda
        import uuid
        import time

        batch_start_time = time.time()

        logger.info(
            "BATCH EXECUTION STARTED",
            total_tasks=len(tasks),
            execution_method="LangChain_abatch_as_completed",
            parallel_execution=True,
        )

        # TODO: Remove this delay, it's just for testing!
        async def execute_task_with_delay(input_dict: dict) -> dict:
            task = input_dict["task"]
            task_index = input_dict["index"]

            task_start_time = time.time()
            logger.info(
                "TASK EXECUTION STARTED",
                task_index=task_index,
                task_description=task.description,
                instructions_length=len(task.instructions) if task.instructions else 0,
            )

            # Add artificial delay for testing parallel execution
            if "Create pageviews trends chart" in task.description:
                delay_seconds = 15
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

            # Create and execute the trends node
            trends_node = TrendsGeneratorNode(self._team, self._user)
            human_message = HumanMessage(content=task.instructions, id=str(uuid.uuid4()))
            input_state = AssistantState(
                messages=[human_message],
                plan="Create a trends chart showing activity over time",
                start_id=human_message.id,
            )

            config = RunnableConfig()
            result = await trends_node.arun(input_state, config)

            task_end_time = time.time()
            task_duration = task_end_time - task_start_time

            logger.info(
                "TASK EXECUTION COMPLETED",
                task_index=task_index,
                task_description=task.description,
                execution_time_seconds=round(task_duration, 2),
                had_artificial_delay="Create pageviews trends chart" in task.description,
                output_available=bool(result),
            )

            return {"task": task, "task_index": task_index, "result": result}

        # Create a runnable from the async function
        task_executor = RunnableLambda(execute_task_with_delay).with_config(run_name="TaskExecutor")

        # Prepare inputs for batch processing
        batch_inputs = [{"task": task, "index": i} for i, task in enumerate(tasks)]

        config = RunnableConfig()

        # Use abatch_as_completed to process tasks as they complete
        async for task_index, output in task_executor.abatch_as_completed(batch_inputs, config=config):
            task = output["task"]
            result = output["result"]

            processing_start_time = time.time()
            logger.info(
                "PROCESSING TASK RESULT",
                task_index=task_index,
                task_description=task.description,
                result_available=bool(result),
            )

            # Process the result
            result_content = self._extract_result_content(result)
            artifacts = self._extract_artifacts(result, task_index)

            # Store artifacts
            for artifact in artifacts:
                self._artifact_store.store_artifact(artifact)

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

    def _extract_result_content(self, subgraph_result) -> str:
        """Extract markdown result content from subgraph execution."""

        # Handle PartialAssistantState result from TrendsGeneratorNode
        if hasattr(subgraph_result, "messages"):
            messages = subgraph_result.messages
        elif isinstance(subgraph_result, dict):
            messages = subgraph_result.get("messages", [])
        else:
            messages = []

        result_parts = []
        for message in messages:
            # Handle different message types
            if isinstance(message, ReasoningMessage):
                # Skip reasoning messages in the final result
                continue
            elif hasattr(message, "content") and message.content:
                # AssistantMessage and other content-based messages
                result_parts.append(message.content)
            elif isinstance(message, VisualizationMessage):
                # VisualizationMessage has different fields
                viz_description = f"Generated visualization"
                if hasattr(message, "plan") and message.plan:
                    viz_description += f": {message.plan}"
                result_parts.append(viz_description)

        if result_parts:
            return "\n\n".join(result_parts)
        else:
            return "Task completed successfully but no detailed results were generated."

    def _extract_artifacts(self, subgraph_result, task_index: int) -> list[ArtifactResult]:
        """Extract artifacts from subgraph execution results."""

        artifacts = []

        # Handle PartialAssistantState result from TrendsGeneratorNode
        if hasattr(subgraph_result, "messages"):
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
                        "visualization_message": message.model_dump()  # Store the entire message
                    },
                )
                artifacts.append(artifact)

        # Check if the result contains any query/insight data that could be an artifact
        has_plan = (hasattr(subgraph_result, "plan") and subgraph_result.plan) or (
            isinstance(subgraph_result, dict) and "plan" in subgraph_result
        )
        has_query = "query" in str(subgraph_result)

        if has_plan or has_query:
            artifact = ArtifactResult(
                short_id=f"insight_{task_index}_{uuid.uuid4().hex[:8]}",
                description=f"Insight generated from task {task_index + 1}",
                artifact_type="InsightArtifact",
                data={"result": subgraph_result, "task_index": task_index},
            )
            artifacts.append(artifact)

        return artifacts
