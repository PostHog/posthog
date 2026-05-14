"""
Logic for auto-detecting test flows via a sandboxed agent.

The agent clones a repository, analyzes it alongside PostHog data,
and proposes the most important user flows to test end-to-end.
"""

from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from posthog.models.team.team import Team
    from posthog.models.user import User

    from products.agentic_tests.backend.models import AgenticTest
    from products.tasks.backend.models import Task, TaskRun

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Output schema — the agent uses `set_output` to produce this structure
# ---------------------------------------------------------------------------


class ProposedTestFlow(BaseModel):
    title: str = Field(description="User-readable title, sentence-cased")
    rationale: str = Field(description="Why this flow matters and what data backs the choice")
    qa_instructions: str = Field(description="Prose instructions for the browser QA agent")
    pass_criteria: str = Field(description="What determines success vs failure")
    expected_duration_seconds: int = Field(description="Timeout for the agent run")
    prerequisites: str = Field(description="Setup steps needed before the test")
    target_url: str = Field(description="The specific starting URL for the test")


class DetectFlowsOutput(BaseModel):
    qa_spec: list[ProposedTestFlow] = Field(description="Ordered list of proposed test flows")


# ---------------------------------------------------------------------------
# Task creation
# ---------------------------------------------------------------------------

_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "proposed_test_flows_prompt.md"


def launch_detect_flows_task(
    *,
    team: "Team",
    user: "User",
    repository: str,
    domain: str,
) -> "Task":
    """Create and run a sandboxed agent task that proposes test flows."""
    from products.tasks.backend.models import Task

    prompt_text = _PROMPT_PATH.read_text()
    description = f"{prompt_text}\n\nThe product is deployed at: {domain}"

    task = Task.create_and_run(
        team=team,
        title=f"Auto-detect test flows for {repository}",
        description=description,
        origin_product=Task.OriginProduct.AGENTIC_TESTS,
        user_id=user.id,
        repository=repository,
        create_pr=False,
        posthog_mcp_scopes="read_only",
        output_schema=DetectFlowsOutput,
    )
    return task


# ---------------------------------------------------------------------------
# Completion handler — called from post_save signal on TaskRun
# ---------------------------------------------------------------------------


def handle_detect_flows_completion(task_run: "TaskRun") -> list["AgenticTest"]:
    """Parse the agent's structured output and create proposed AgenticTest instances."""
    from products.agentic_tests.backend.models import AgenticTest

    output = DetectFlowsOutput.model_validate(task_run.output)

    tests_to_create: list[AgenticTest] = []
    for flow in output.qa_spec:
        prompt_parts = [
            flow.qa_instructions.strip(),
            f"\nPass criteria:\n{flow.pass_criteria.strip()}",
            f"\nPrerequisites:\n{flow.prerequisites.strip()}",
            f"\nExpected duration: {flow.expected_duration_seconds}s",
        ]
        tests_to_create.append(
            AgenticTest(
                team_id=task_run.task.team_id,
                created_by=task_run.task.created_by,
                name=flow.title,
                description=flow.rationale,
                prompt="\n".join(prompt_parts),
                target_url=flow.target_url,
                status=AgenticTest.Status.PROPOSED,
            )
        )

    created = AgenticTest.objects.bulk_create(tests_to_create)
    logger.info(
        "detect_flows.proposed_tests_created",
        task_id=str(task_run.task_id),
        count=len(created),
    )
    return created
