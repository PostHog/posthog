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
        logger.info("DeepResearchPlannerNode starting")

        # Find the latest human message
        human_message = None
        for message in reversed(state.messages or []):
            if isinstance(message, HumanMessage):
                human_message = message
                break

        if not human_message:
            logger.error("No human message found")
            return PartialAgentSubgraphState(plan="No message provided", current_step=None)

        # Extract DEEP_RESEARCH JSON from the message
        content = human_message.content
        if not content or not isinstance(content, str):
            logger.error("Invalid message content")
            return PartialAgentSubgraphState(plan="Invalid message format", current_step=None)

        # Parse the DEEP_RESEARCH command
        if "DEEP_RESEARCH" in content:
            # Extract JSON after DEEP_RESEARCH keyword
            try:
                json_start = content.index("DEEP_RESEARCH") + len("DEEP_RESEARCH")
                json_str = content[json_start:].strip()

                # Parse the JSON
                research_data = json.loads(json_str)

                # Convert to TaskDefinition format
                tasks = []
                for task_data in research_data.get("tasks", []):
                    # Handle both "prompt" and "instructions" fields for compatibility
                    instructions = task_data.get("prompt") or task_data.get("instructions", "")

                    task = TaskDefinition(
                        description=task_data.get("description", "Unknown task"),
                        instructions=instructions,
                        artifact_short_ids=task_data.get("artifact_short_ids"),
                    )
                    tasks.append(task)

                # Create a research step with all tasks
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
                )

                logger.info("Created research step", step_id=research_step.id, num_tasks=len(tasks))

                return PartialAgentSubgraphState(
                    plan=f"Executing {len(tasks)} research tasks", current_step=research_step
                )

            except (json.JSONDecodeError, ValueError) as e:
                logger.exception("Failed to parse DEEP_RESEARCH JSON", error=str(e))
                return PartialAgentSubgraphState(plan=f"Failed to parse research request: {str(e)}", current_step=None)
        else:
            # Fallback: treat the entire message as a single task
            research_step = DeepResearchPlanStep(
                id=str(uuid.uuid4()),
                title="Research Task",
                description=json.dumps({"tasks": [{"description": "User research request", "instructions": content}]}),
                type="parallel_tasks",
            )

            return PartialAgentSubgraphState(plan="Executing research request", current_step=research_step)

    def router(self, state: AgentSubgraphState) -> str:
        """
        Route to the agent subgraph executor if we have a step, otherwise end.
        """
        if state.current_step:
            return "execute"
        return "end"
