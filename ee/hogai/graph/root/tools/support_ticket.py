from typing import Literal

from pydantic import BaseModel, Field

from posthog.schema import SupportTicketMessage

from ee.hogai.tool import MaxTool, ToolMessagesArtifact

from ..prompts import SUPPORT_ESCALATION_SCENARIOS_PROMPT

SUPPORT_TICKET_TOOL_PROMPT = f"""
Use this tool to create a support ticket when the user needs human assistance beyond what Max can provide.

# When to use this tool

Use this tool proactively in these situations:

{SUPPORT_ESCALATION_SCENARIOS_PROMPT}

# What this tool does

This tool captures the conversation context and creates a support ticket with:
- A summary of the user's issue
- The full conversation history for context
- Appropriate categorization and priority level
- All relevant technical details discussed

# Examples of when to use

<example>
User: "I've tried everything you've suggested but my events still aren't showing up. This is really frustrating."
Assistant: I can see you've tried multiple approaches and this is causing frustration. Let me create a support ticket so our team can investigate your specific setup and help resolve this events tracking issue.
*Uses support ticket tool with summary and conversation context*
</example>

<example>
User: "Max, I think there's a bug with feature flags. They're not working as expected and I've followed all the docs."
Assistant: That does sound like it could be a bug. Let me create a support ticket with all the details we've discussed so our engineering team can investigate this feature flag issue.
*Uses support ticket tool to report the potential bug*
</example>

<example>
User: "PostHog does't support the integration I need as a data warehouse source. I'd like you to add it"
Assistant: It would be great if PostHog supported that integration in the future! Let me create a support ticket so we can raise a feature request for you!
*Uses support ticket tool to raise a feature request*
</example>

# Guidelines

- Always include a clear, concise summary of the user's main issue, writing it as if you were the user.
- Choose appropriate target area and priority level based on the issue
- Suggest this tool when you've genuinely exhausted other avenues for help
- Don't overuse – only when human assistance is truly needed
- Note: Support team will have access to the full conversation history automatically
""".strip()


class CreateSupportTicketToolArgs(BaseModel):
    user_summary: str = Field(
        description="A clear, concise summary written on behalf of the user, describing their main issue or question (1-2 sentences max)"
    )
    # NOTE: These values must match SupportTicketTargetArea in frontend/src/lib/components/Support/supportLogic.ts
    # If you update this list, also update the frontend type definition
    suggested_area: Literal[
        "experiments",
        "apps",
        "login",
        "billing",
        "onboarding",
        "cohorts",
        "data_management",
        "notebooks",
        "data_warehouse",
        "feature_flags",
        "analytics",
        "session_replay",
        "toolbar",
        "surveys",
        "web_analytics",
        "error_tracking",
        "cdp_destinations",
        "data_ingestion",
        "batch_exports",
        "workflows",
        "platform_addons",
        "max-ai",
        "customer-analytics",
    ] = Field(
        description="The most appropriate target area for this ticket based on the user's issue", default="max-ai"
    )
    # NOTE: These values must match SupportTicketSeverityLevel keys in frontend/src/lib/components/Support/supportLogic.ts
    # If you update this list, also update SEVERITY_LEVEL_TO_NAME in the frontend
    priority: Literal["low", "medium", "high", "critical"] = Field(
        description="Priority level based on the severity of the issue", default="medium"
    )


class CreateSupportTicketTool(MaxTool):
    name: str = "create_support_ticket"
    description: str = SUPPORT_TICKET_TOOL_PROMPT
    thinking_message: str = "Drafting a message for support"

    args_schema: type[BaseModel] = CreateSupportTicketToolArgs

    async def _arun_impl(
        self, user_summary: str, suggested_area: str = "max-ai", priority: str = "medium"
    ) -> tuple[str, ToolMessagesArtifact]:
        """
        Create the basis for a support ticket from a Max conversation.

        This tool prepares the support ticket data and provides instructions for the frontend
        to display the ticket creation interface to the user.
        """

        if not user_summary or not user_summary.strip():
            # For now, let's assume the LLM won't call this without proper args
            # If this becomes an issue, we can create an error message instead
            raise ValueError("user_summary is required for creating a support ticket")

        ticket_data = {
            "summary": user_summary,
            "target_area": suggested_area,
            "priority": priority,
        }

        # Create the inline support ticket message
        support_ticket_message = SupportTicketMessage(ticket_data=ticket_data)

        return (
            "Here's a draft support ticket with a summary of your conversation. You can review and submit it below:",
            ToolMessagesArtifact(messages=[support_ticket_message]),
        )
