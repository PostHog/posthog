"""
Deep Research Planner Node that parses DEEP_RESEARCH commands and creates research steps.
"""

import json
import uuid

import structlog
from langchain_core.runnables import RunnableConfig

from ee.hogai.graph.base import BaseAssistantNode
from ee.hogai.utils.types import (
    AgentSubgraphState,
    PartialAgentSubgraphState,
    DeepResearchPlanStep,
    TaskDefinition,
    TaskStatus,
)
from posthog.models import Team, User
from posthog.schema import HumanMessage

logger = structlog.get_logger(__name__)


class DeepResearchPlannerNode(BaseAssistantNode[AgentSubgraphState, PartialAgentSubgraphState]):
    """
    Node that parses DEEP_RESEARCH commands and creates research steps.

    This node:
    1. Extracts the DEEP_RESEARCH JSON from the message
    2. Converts tasks into a DeepResearchPlanStep
    3. Sets up the state for the agent subgraph to execute
    """

    def __init__(self, team: Team, user: User):
        super().__init__(team, user)

    async def arun(self, state: AgentSubgraphState, config: RunnableConfig) -> PartialAgentSubgraphState:
        """
        Parse the DEEP_RESEARCH command and create a research step.
        """
        logger.info(
            "DeepResearchPlannerNode starting",
            messages_count=len(state.messages or []),
            message_types=[type(msg).__name__ for msg in (state.messages or [])],
            has_current_step=bool(state.current_step),
            current_step_status=state.current_step.status if state.current_step else None,
        )

        # If we already have a current step, don't create a new one - just pass through
        if state.current_step:
            logger.info(
                "Planner: Current step already exists, passing through",
                step_id=state.current_step.id,
                status=state.current_step.status,
                messages_in_state=len(state.messages or []),
                returning_empty_partial=True,
            )

            # If the step is completed, we want to clean up the conversation
            # Remove the original command and any duplicate messages
            if state.current_step.status == "completed":
                logger.info(
                    "Planner: Analyzing completed step messages",
                    message_details=[
                        (
                            i,
                            type(msg).__name__,
                            str(msg.content)[:50] + "..." if hasattr(msg, "content") else "no content",
                        )
                        for i, msg in enumerate(state.messages or [])
                    ],
                    total_messages=len(state.messages or []),
                )

                # Filter out human messages (original commands) and keep only results
                filtered_messages = [msg for msg in (state.messages or []) if not isinstance(msg, HumanMessage)]

                logger.info(
                    "Planner: Cleaning up completed step messages",
                    original_count=len(state.messages or []),
                    filtered_count=len(filtered_messages),
                    removed_human_messages=len(state.messages or []) - len(filtered_messages),
                    filtered_message_types=[type(msg).__name__ for msg in filtered_messages],
                )

                # Return the filtered messages to replace the state messages
                return PartialAgentSubgraphState(messages=filtered_messages)

            return PartialAgentSubgraphState()

        content = state.messages[-1].content
        if "DEEP_RESEARCH" in content:
            # Extract JSON after `DEEP_RESEARCH` keyword
            try:
                json_start = content.index("DEEP_RESEARCH") + len("DEEP_RESEARCH")
                json_str = content[json_start:].strip()

                research_data = json.loads(json_str)

                tasks = []
                task_statuses = []
                for i, task_data in enumerate(research_data.get("tasks", [])):
                    instructions = task_data.get("prompt")
                    task_description = task_data.get("description")

                    task = TaskDefinition(
                        description=task_description,
                        instructions=instructions,
                        artifact_short_ids=task_data.get("artifact_short_ids"),
                    )
                    tasks.append(task)

                    task_status = TaskStatus(task_id=f"task_{i}", description=task_description, status="pending")
                    task_statuses.append(task_status)

                step_description = json.dumps(
                    {
                        "tasks": [
                            {
                                "description": t.description,
                                "instructions": t.instructions,
                                "artifact_short_ids": t.artifact_short_ids,
                            }
                            for t in tasks
                        ]
                    }
                )

                research_step = DeepResearchPlanStep(
                    id=str(uuid.uuid4()),
                    title="Execute Research Tasks",
                    description=step_description,
                    type="parallel_tasks",
                    status="in_progress",
                    task_statuses=task_statuses,
                )

                logger.info("Created research step", step_id=research_step.id, num_tasks=len(tasks))

                return PartialAgentSubgraphState(
                    plan=f"Executing {len(tasks)} research tasks", current_step=research_step
                )

            except (json.JSONDecodeError, ValueError) as e:
                logger.exception("Failed to parse DEEP_RESEARCH JSON", error=str(e))
                return PartialAgentSubgraphState(plan=f"Failed to parse research request: {str(e)}", current_step=None)

    def router(self, state: AgentSubgraphState) -> str:
        """
        Route to the agent subgraph executor if we have a step that hasn't been executed,
        otherwise go to end.
        """
        if not state.current_step:
            logger.info("Router: No current step, routing to end")
            return "end"

        current_status = state.current_step.status
        logger.info("Router: Current step status", status=current_status, step_id=state.current_step.id)

        # Check overall status
        if current_status in ["completed", "failed"]:
            logger.info("Router: Step completed/failed, routing to end")
            return "end"

        # Still have work to do (pending or in_progress)
        logger.info("Router: Step still pending/in_progress, routing to execute")
        return "execute"
