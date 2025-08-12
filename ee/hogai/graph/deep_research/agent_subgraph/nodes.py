import json
import time
import uuid
import structlog

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer

from ee.hogai.graph.base import BaseAssistantNode
from .tools import ExecuteTasksTool
from posthog.models import Team, User
from posthog.schema import AssistantMessage, VisualizationMessage, HumanMessage

from ee.hogai.utils.types import (
    AgentSubgraphState,
    PartialAgentSubgraphState,
    DeepResearchPlanStep,
    TaskDefinition,
    TaskStatus,
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

    def __init__(self, team: Team, user: User, insights_subgraph):
        super().__init__(team, user)
        # Initialize the execute_tasks tool for parallel execution with insights subgraph
        self._execute_tasks_tool = ExecuteTasksTool(team, user, insights_subgraph)

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

        # Initialize task statuses if not already present
        task_statuses = list(step.task_statuses) if step.task_statuses else []
        if not task_statuses:
            # Create task statuses if they don't exist
            task_statuses = [
                TaskStatus(task_id=f"task_{i}", description=task.description, status="pending")
                for i, task in enumerate(tasks)
            ]

        # Create a map for quick lookup and updates
        task_status_map = {ts.task_id: ts for ts in task_statuses}

        try:
            # Debug: Check what messages are in the current state
            logger.info(
                "TaskExecutor: Starting with state messages",
                state_messages_count=len(state.messages or []),
                state_message_types=[type(msg).__name__ for msg in (state.messages or [])],
                state_has_human_messages=any(isinstance(msg, HumanMessage) for msg in (state.messages or [])),
            )

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

            writer = get_stream_writer()

            # Stream initial task start message
            start_message = AssistantMessage(
                content=f"🚀 Starting {len(tasks)} research tasks in parallel...", id=str(uuid.uuid4())
            )
            messages.append(start_message)
            writer(start_message)

            async for task_result in self._execute_tasks_tool.arun(tasks, config):
                task_count += 1
                current_time = time.time()
                elapsed_total = current_time - execution_start_time

                # Update task status for this completed task using task_id
                task_id = f"task_{task_count - 1}"
                if task_id in task_status_map:
                    task_status_map[task_id].status = "completed"
                    task_status_map[task_id].result_summary = (
                        task_result.result[:100] if task_result.result else "Task completed"
                    )

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

                # Add a "Finished task" message for streaming with progress
                progress_percentage = round((task_count / len(tasks)) * 100, 1)
                finished_message = AssistantMessage(
                    content=f"✅ **Task {task_count}/{len(tasks)} Complete** ({progress_percentage}%)\n\n**{task_result.description}**",
                    id=str(uuid.uuid4()),
                )
                messages.append(finished_message)
                writer(finished_message)

                # Extract VisualizationMessage objects from artifacts
                current_viz_messages = []
                if task_result.artifacts:
                    for artifact in task_result.artifacts:
                        if artifact.artifact_type == "VisualizationMessage":
                            # Get the stored VisualizationMessage object directly
                            viz_msg = artifact.data.get("visualization_message")
                            if viz_msg and isinstance(viz_msg, VisualizationMessage):
                                try:
                                    visualization_messages.append(viz_msg)
                                    current_viz_messages.append(viz_msg)
                                    messages.append(viz_msg)

                                    # Stream the visualization message immediately to the user
                                    writer(viz_msg)

                                    logger.info("Retrieved and streamed VisualizationMessage", viz_id=viz_msg.id)
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
                    created_assistant_messages=2,  # Finished message + any visualization
                    created_visualizations=num_viz_messages,
                    processing_time_ms=round(processing_elapsed * 1000, 2),
                    total_messages_accumulated=len(messages),
                    total_visualizations_accumulated=len(visualization_messages),
                    completion_status="success" if task_result.result else "completed_no_content",
                    finished_message_added=True,
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

            # Convert map back to list for consistency
            updated_task_statuses = list(task_status_map.values())

            # Check if all tasks are completed
            all_completed = all(t.status == "completed" for t in updated_task_statuses)
            any_failed = any(t.status == "failed" for t in updated_task_statuses)

            # Determine overall status
            if any_failed:
                overall_status = "failed"
            elif all_completed:
                overall_status = "completed"
            else:
                overall_status = "in_progress"

            logger.info(
                "TaskExecutor: Final status determination",
                total_tasks=len(updated_task_statuses),
                completed_tasks=sum(1 for t in updated_task_statuses if t.status == "completed"),
                failed_tasks=sum(1 for t in updated_task_statuses if t.status == "failed"),
                overall_status=overall_status,
            )

            # Add completion message when all tasks are completed
            if overall_status == "completed":
                summary_content = f"✅ **Deep Research Completed**\n\n"
                summary_content += f"Successfully completed {task_count}/{len(tasks)} research tasks:\n\n"

                for task_status in updated_task_statuses:
                    status_emoji = "✅" if task_status.status == "completed" else "❌"
                    summary_content += f"{status_emoji} **{task_status.description}**\n"
                    if task_status.result_summary:
                        summary_content += f"   - {task_status.result_summary}\n"
                    summary_content += "\n"

                summary_message = AssistantMessage(content=summary_content, id=str(uuid.uuid4()))
                messages.append(summary_message)

                # Stream the completion summary message immediately
                writer(summary_message)

                logger.info("Added completion summary message")

            # Extract IDs from visualization messages
            viz_ids = [msg.id for msg in visualization_messages if msg.id]

            # Create updated step with task statuses
            updated_step = DeepResearchPlanStep(
                id=step.id,
                title=step.title,
                description=step.description,
                type=step.type,
                status=overall_status,
                result_summary=f"Completed {task_count}/{len(tasks)} tasks",
                visualization_messages=viz_ids,
                task_statuses=updated_task_statuses,
            )

            # Filter out human messages (original commands) + visualization messages
            # Visualization messages are streamed directly, not added to messages list
            filtered_messages = [
                msg
                for msg in messages
                if not isinstance(msg, HumanMessage) and not isinstance(msg, VisualizationMessage)
            ]

            logger.info(
                "TaskExecutor: Returning filtered messages",
                total_messages=len(filtered_messages),
                original_messages=len(messages),
                filtered_out=len(messages) - len(filtered_messages),
                message_types=[type(msg).__name__ for msg in filtered_messages],
                has_completion_message=any(
                    "Deep Research Completed" in str(getattr(msg, "content", "")) for msg in filtered_messages
                ),
            )

            return PartialAgentSubgraphState(
                current_step=updated_step,
                messages=filtered_messages,  # Only new messages, filtered to avoid DEEP_RESEARCH duplicates
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
            # Handle case where description contains "DEEP_RESEARCH" prefix
            json_str = description
            if "DEEP_RESEARCH" in description:
                # Extract JSON after DEEP_RESEARCH keyword
                json_start = description.index("DEEP_RESEARCH") + len("DEEP_RESEARCH")
                json_str = description[json_start:].strip()

            data = json.loads(json_str)
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

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.exception(
                "Error parsing tasks from description", error=str(e), description_preview=description[:100]
            )
            # Fallback: create a single task from the description
            return [
                TaskDefinition(description="Parse and execute tasks", instructions=description, artifact_short_ids=None)
            ]
