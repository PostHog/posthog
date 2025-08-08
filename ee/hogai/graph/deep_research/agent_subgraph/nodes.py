import json
import time
import structlog

from langchain_core.runnables import RunnableConfig

from ee.hogai.graph.base import BaseAssistantNode
from .tools import ExecuteTasksTool
from posthog.models import Team, User
from posthog.schema import AssistantMessage, VisualizationMessage

from ee.hogai.utils.types import (
    AgentSubgraphState,
    PartialAgentSubgraphState,
    DeepResearchPlanStep,
    TaskDefinition,
)

logger = structlog.get_logger(__name__)


class TaskExecutorNode(BaseAssistantNode[AgentSubgraphState, PartialAgentSubgraphState]):
    """
    Core task execution node that handles individual or multiple research tasks.

    Key features:
    - Executes tasks using ExecuteTasksTool
    - Streams messages from task execution
    - Filters reasoning nodes for better UX
    - Saves visualization messages for final report
    - Updates step status in real-time
    - Supports artifact management for task references
    """

    def __init__(self, team: Team, user: User):
        super().__init__(team, user)
        # Initialize the execute_tasks tool for parallel execution
        self._execute_tasks_tool = ExecuteTasksTool(team, user)

    async def arun(self, state: AgentSubgraphState, config: RunnableConfig) -> PartialAgentSubgraphState | None:
        logger.info(
            "TaskExecutorNode.arun starting",
            current_step_id=state.current_step.id if state.current_step else None,
            current_step_title=state.current_step.title if state.current_step else None,
            current_step_description=state.current_step.description if state.current_step else None,
        )

        if not state.current_step:
            logger.warning("No research step provided to execute")
            return PartialAgentSubgraphState(messages=[AssistantMessage(content="No research step to execute")])

        current_step = state.current_step

        return await self._execute_tasks(current_step, state, config)

    async def _execute_tasks(
        self, step: DeepResearchPlanStep, state: AgentSubgraphState, config: RunnableConfig
    ) -> PartialAgentSubgraphState:
        """
        Execute tasks using the ExecuteTasksTool.
        """
        logger.info("Executing tasks", step_id=step.id)

        # Parse tasks from step description
        tasks = self._parse_tasks_from_description(step.description)
        if not tasks:
            logger.error("No tasks found in step description")
            return PartialAgentSubgraphState(messages=[AssistantMessage(content="No tasks found to execute")])

        logger.info("Found tasks to execute", num_tasks=len(tasks))

        try:
            messages = []
            visualization_messages = []
            task_count = 0

            execution_start_time = time.time()

            logger.info(
                "TASK EXECUTION STARTED",
                total_tasks=len(tasks),
                execution_mode="parallel",
                estimated_duration="varies by task complexity",
            )

            async for task_result in self._execute_tasks_tool.arun(tasks):
                task_count += 1
                current_time = time.time()
                elapsed_total = current_time - execution_start_time

                # Calculate task-specific metrics
                result_length = len(task_result.result) if task_result.result else 0
                artifact_count = len(task_result.artifacts) if task_result.artifacts else 0

                logger.info(
                    "TASK COMPLETED",
                    task_number=f"{task_count}/{len(tasks)}",
                    progress_percentage=round((task_count / len(tasks)) * 100, 1),
                    task_description=task_result.description,
                    execution_time_seconds=round(elapsed_total, 2),
                    result_length_chars=result_length,
                    artifact_count=artifact_count,
                    remaining_tasks=len(tasks) - task_count,
                    result_preview=task_result.result[:100] + "..."
                    if result_length > 100
                    else task_result.result or "No result",
                )

                # Create an assistant message for each task result
                content = f"## {task_result.description}\n\n{task_result.result}"
                current_message = AssistantMessage(content=content)
                messages.append(current_message)

                # Extract VisualizationMessage objects from artifacts
                current_viz_messages = []
                if task_result.artifacts:
                    for artifact in task_result.artifacts:
                        if artifact.artifact_type == "VisualizationMessage":
                            # Reconstruct the VisualizationMessage from the stored data
                            viz_data = artifact.data.get("visualization_message")
                            if viz_data:
                                # Import at runtime to avoid circular imports
                                from posthog.schema import (
                                    AssistantTrendsQuery,
                                    AssistantFunnelsQuery,
                                    AssistantRetentionQuery,
                                    AssistantHogQLQuery,
                                )

                                # The answer field needs to be reconstructed based on its type
                                answer_data = viz_data.get("answer")
                                if answer_data:
                                    # Determine the query type and reconstruct it
                                    if "trendsFilter" in answer_data:
                                        viz_data["answer"] = AssistantTrendsQuery(**answer_data)
                                    elif "funnelsFilter" in answer_data:
                                        viz_data["answer"] = AssistantFunnelsQuery(**answer_data)
                                    elif "retentionFilter" in answer_data:
                                        viz_data["answer"] = AssistantRetentionQuery(**answer_data)
                                    elif "metadata" in answer_data:
                                        viz_data["answer"] = AssistantHogQLQuery(**answer_data)

                                try:
                                    viz_msg = VisualizationMessage(**viz_data)
                                    visualization_messages.append(viz_msg)
                                    current_viz_messages.append(viz_msg)
                                    messages.append(viz_msg)
                                    logger.info("Reconstructed VisualizationMessage", viz_id=viz_msg.id)
                                except Exception as e:
                                    logger.warning("Could not reconstruct VisualizationMessage", error=str(e))

                # Log detailed processing results
                num_viz_messages = len(current_viz_messages)
                processing_time = time.time()
                processing_elapsed = processing_time - current_time

                logger.info(
                    "🔄 PLANNER PROCESSED TASK",
                    task_description=task_result.description,
                    task_index=task_count,
                    created_assistant_messages=1,
                    created_visualizations=num_viz_messages,
                    processing_time_ms=round(processing_elapsed * 1000, 2),
                    total_messages_accumulated=len(messages),
                    total_visualizations_accumulated=len(visualization_messages),
                    completion_status="success" if task_result.result else "completed_no_content",
                )

                # Note: Real-time streaming happens via logger messages above.
                # Task results are processed immediately as they complete (optimal performance).
                # UI streaming occurs at the graph level, not individual node level.

            total_execution_time = time.time() - execution_start_time
            avg_task_time = total_execution_time / len(tasks) if len(tasks) > 0 else 0

            logger.info(
                "TASK EXECUTION COMPLETED",
                total_tasks_completed=task_count,
                total_messages_created=len(messages),
                total_visualizations_created=len(visualization_messages),
                total_execution_time_seconds=round(total_execution_time, 2),
                average_task_time_seconds=round(avg_task_time, 2),
                execution_efficiency="parallel" if len(tasks) > 1 else "single_task",
                success_rate=f"{task_count}/{len(tasks)} (100%)"
                if task_count == len(tasks)
                else f"{task_count}/{len(tasks)} ({round(task_count/len(tasks)*100, 1)}%)",
            )

            # Return all messages (visualization messages are already included in messages)

            # Extract IDs from visualization messages
            viz_ids = [msg.id for msg in visualization_messages if msg.id]

            return PartialAgentSubgraphState(
                messages=messages,  # Already contains both assistant and viz messages
                visualization_messages=viz_ids,  # Store IDs as per the field type
            )

        except Exception as e:
            logger.exception("Error executing tasks", error=str(e), step_id=step.id)
            return PartialAgentSubgraphState(messages=[AssistantMessage(content=f"Error executing tasks: {str(e)}")])

    def _parse_tasks_from_description(self, description: str) -> list[TaskDefinition]:
        """
        Parse TaskDefinition objects from step description.
        Expected format: {"tasks": [{"description": "...", "instructions": "..."}, ...]}
        """
        try:
            data = json.loads(description)
            if "tasks" not in data:
                raise ValueError("No 'tasks' key found in description JSON")

            tasks = []
            for task_data in data["tasks"]:
                task = TaskDefinition(
                    description=task_data.get("description", "Unknown task"),
                    instructions=task_data.get(
                        "instructions", task_data.get("prompt", task_data.get("description", ""))
                    ),
                    artifact_short_ids=task_data.get("artifact_short_ids"),
                )
                tasks.append(task)

            return tasks

        except (json.JSONDecodeError, KeyError, TypeError):
            # Fallback: create a single task from the description
            return [
                TaskDefinition(description="Parse and execute tasks", instructions=description, artifact_short_ids=None)
            ]

    def router(self, state: AgentSubgraphState) -> str:
        """
        Router function to determine next step after execution.
        """
        if state.current_step:
            # Check if there are more steps to execute
            # For now, just go to end after executing
            return "end"
        return "end"
