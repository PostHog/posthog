import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from posthog.schema import ArtifactContentType, ArtifactSource, AssistantTool, AssistantToolCallMessage

from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.tools.create_notebook.helpers import ArtifactStatus, create_or_update_notebook_artifact

FINALIZE_PLAN_PROMPT = """
Use this tool to present your completed plan to the user for approval. This will create a notebook artifact with the plan content.

# When to use this tool
- You have gathered enough data and insights to form a complete plan
- You are ready to present your findings with supporting visualizations
- You are ready to move to executing your plan

# When NOT to use this tool
- You are still gathering data or running queries
- You need more information before forming conclusions

# Plan structure
Write your plan in markdown with clear sections. Each section should answer a specific question or present a single finding.

## Format guidelines
- Use `#` and `##` headings to organize sections
- Keep explanations concise - let the data speak
- One insight per section, don't repeat visualizations
- Use bullet points for recommendations or action items

# Example
```markdown
# Plan: Investigate Signup Drop-off

## Goal
Identify why users are abandoning the signup flow and recommend fixes.

## Investigation Steps

### 1. Analyze Current Funnel
Query the signup funnel to identify which step has the highest drop-off rate.

### 2. Segment by User Properties
Break down conversion by device type, traffic source, and user country to find patterns.

### 3. Examine Session Recordings
Review recordings of users who dropped off at the problem step to understand friction points.

### 4. Compare with Historical Data
Check if drop-off increased after recent changes by comparing week-over-week metrics.

## Expected Deliverables
- Funnel visualization with drop-off rates per step
- Breakdown charts by key segments
- Specific recommendations based on findings
```

# Updating existing plan notebooks:
- If you want to update an existing plan notebook, use the `artifact_id` parameter to specify the ID of the existing artifact
- *IMPORTANT*: Updating a plan notebook will replace the existing content with the new content
""".strip()


class FinalizePlanToolArgs(BaseModel):
    title: str = Field(description="A descriptive title for the plan.")
    plan: str = Field(
        description="The plan content in markdown format.",
    )
    artifact_id: str | None = Field(
        default=None, description="The ID of an existing plan notebook artifact that you want to update."
    )


class FinalizePlanTool(MaxTool):
    name: Literal[AssistantTool.FINALIZE_PLAN] = AssistantTool.FINALIZE_PLAN
    args_schema: type[BaseModel] = FinalizePlanToolArgs
    description: str = FINALIZE_PLAN_PROMPT

    async def is_dangerous_operation(self, **kwargs) -> bool:
        """Finalizing a plan always requires user approval or rejection."""
        return True

    async def format_dangerous_operation_preview(self, **kwargs) -> str:
        """
        Build a rich preview showing plan details and what will be modified.
        """
        plan = kwargs.get("plan")
        if not plan:
            return f"Execute {self.name} operation"

        return f"PostHog AI's plan:\n\n{plan}"

    async def _arun_impl(
        self,
        title: str,
        plan: str,
        artifact_id: str | None = None,
    ) -> tuple[str, Any]:
        artifact, status = await create_or_update_notebook_artifact(
            artifacts_manager=self._context_manager.artifacts,
            content=plan,
            title="PostHog AI's plan: " + title,
            artifact_id=artifact_id,
        )

        message = f"The plan notebook artifact has been created with artifact_id: {artifact.short_id}."
        if status == ArtifactStatus.FAILED_TO_UPDATE:
            message = f"Failed to update the existing plan notebook artifact. A new artifact has been created with artifact_id: {artifact.short_id}."
        elif status == ArtifactStatus.UPDATED:
            message = f"The plan notebook artifact with artifact_id {artifact_id} has been updated."

        message += " The user has approved the plan. You can now start executing the plan."

        artifact_message = self._context_manager.artifacts.create_message(
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
            content_type=ArtifactContentType.NOTEBOOK,
        )

        return "", ToolMessagesArtifact(
            messages=[
                artifact_message,
                AssistantToolCallMessage(content=message, tool_call_id=self.tool_call_id, id=str(uuid.uuid4())),
            ]
        )
