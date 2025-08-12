import json
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
    Core task execution node that handles research tasks (TO-DOs coming from the Deep Research Planner).
    """

    def __init__(self, team: Team, user: User, insights_subgraph):
        super().__init__(team, user)
        self._execute_tasks_tool = ExecuteTasksTool(team, user, insights_subgraph)

    async def arun(self, state: AgentSubgraphState, config: RunnableConfig) -> PartialAgentSubgraphState | None:
        if not state.current_step:
            logger.warning("No research step provided to execute")
            return PartialAgentSubgraphState(messages=[AssistantMessage(content="No research step to execute")])

        current_step = state.current_step

        return await self._execute_tasks(current_step, state, config)

    async def _execute_tasks(
        self, step: DeepResearchPlanStep, _: AgentSubgraphState, config: RunnableConfig
    ) -> PartialAgentSubgraphState:
        # Parse tasks from step description
        tasks = self._parse_tasks_from_description(step.description)
        if not tasks:
            return PartialAgentSubgraphState(messages=[AssistantMessage(content="No tasks found to execute")])

        # Initialize task statuses if not already present
        task_statuses = list(step.task_statuses) if step.task_statuses else []
        if not task_statuses:
            task_statuses = [
                TaskStatus(task_id=f"task_{i}", description=task.description, status="pending")
                for i, task in enumerate(tasks)
            ]

        # Create a map for quick lookup and updates
        task_status_map = {ts.task_id: ts for ts in task_statuses}

        try:
            messages = []
            visualization_messages = []
            task_count = 0

            writer = get_stream_writer()

            # Stream initial task start message
            start_message = AssistantMessage(
                content=f"🚀 Starting {len(tasks)} research tasks in parallel...", id=str(uuid.uuid4())
            )
            messages.append(start_message)
            writer(start_message)

            async for task_result in self._execute_tasks_tool.arun(tasks, config):
                task_count += 1

                # Update task status
                task_id = f"task_{task_count - 1}"
                if task_id in task_status_map:
                    task_status_map[task_id].status = "completed"
                    task_status_map[task_id].result_summary = (
                        task_result.result[:100] if task_result.result else "Task completed"
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
                            viz_msg = artifact.data.get("visualization_message")
                            if viz_msg and isinstance(viz_msg, VisualizationMessage):
                                try:
                                    visualization_messages.append(viz_msg)
                                    current_viz_messages.append(viz_msg)
                                    messages.append(viz_msg)
                                    writer(viz_msg)
                                except Exception:
                                    pass

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
                writer(summary_message)

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

            return PartialAgentSubgraphState(
                current_step=updated_step,
                messages=filtered_messages,
                visualization_messages=viz_ids,
            )

        except Exception as e:
            logger.exception("Error executing tasks", error=str(e), step_id=step.id)
            return PartialAgentSubgraphState(messages=[AssistantMessage(content=f"Error executing tasks: {str(e)}")])

    def _parse_tasks_from_description(self, description: str) -> list[TaskDefinition]:
        """
        Parse TaskDefinition objects from step description.
        Expected format: {"tasks": [{"description": "...", "instructions": "..."}, ...]}
        """
        json_str = description
        if "DEEP_RESEARCH" in description:
            json_start = description.index("DEEP_RESEARCH") + len("DEEP_RESEARCH")
            json_str = description[json_start:].strip()

        data = json.loads(json_str)
        if "tasks" not in data:
            raise ValueError("No 'tasks' key found in description JSON")

        tasks = []
        for task_data in data["tasks"]:
            task = TaskDefinition(
                description=task_data.get("description", "Unknown task"),
                instructions=task_data.get("instructions", task_data.get("prompt", task_data.get("description", ""))),
                artifact_short_ids=task_data.get("artifact_short_ids"),
            )
            tasks.append(task)

        return tasks
