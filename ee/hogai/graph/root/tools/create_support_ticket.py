from typing import Literal

from pydantic import BaseModel, Field

from posthog.schema import DraftSupportTicketToolOutput

from ee.hogai.tool import MaxTool

SUPPORT_ESCALATION_PROMPT = f"""<support_escalation>
You have access to the `create_support_ticket` tool to escalate issues to human support when needed.

IMPORTANT: Don't overuse this tool. Only escalate when human assistance is genuinely needed after you've exhausted your capabilities or you judge that a human intervention will have a more positive outcome than continuing the conversation.

Use this tool in these situations:

1. **You are uncertain about answers** – when search results lack quality info that allows confident responses
2. **User expresses frustration** – when the user shows signs of frustration or dissatisfaction with Max or PostHog
3. **Troubleshooting isn't working** – when you've tried multiple troubleshooting approaches without success
4. **User explicitly asks for human help** – when the user directly requests to speak with support or a human
5. **Going in circles** – when the conversation is repeating without making progress toward resolution
6. **Complex configuration issues** – when the user needs assistance with advanced setup or configuration beyond docs
7. **Billing or account issues** – only escalate to support when the user has admin access but you cannot resolve their billing/account questions, see <billing_context>
8. **Bug reports** – when the user reports what appears to be a genuine bug that needs investigation
9. **Feature requests** – when the user wants to request a new feature or significant enhancement to a PostHog product

When escalating, provide a clear summary written as if you were the user of the issue including conversation context so support can understand the situation immediately. Do not include the user's sentiment in the summary - just state the facts around the issue they are faced with. If the user seems angry or frustrated, acknowledge their feelings but try to diffuse that by writing a calm, empathetic summary.

You will need to select the priority level and target area for the issue.

Note that the support team will have access to the full conversation history automatically, so you don't need to include that in the summary.

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
</support_escalation>""".strip()

TARGET_AREA_DESCRIPTIONS = {
    "experiments": "A/B testing, feature experiments, and statistical analysis",
    "apps": "PostHog apps, plugins, and integrations with third-party services",
    "login": "Authentication, SSO, SAML, user management, and access issues",
    "billing": "Pricing, invoices, subscription management, and payment issues",
    "onboarding": "Getting started, initial setup, and product guidance",
    "cohorts": "User segments, behavioral cohorts, and dynamic groups",
    "data_management": "Data management including event/property definitions and actions",
    "notebooks": "Analysis notebooks, templates, and collaborative features",
    "data_warehouse": "Data warehouse connections, external data sources, and SQL queries",
    "feature_flags": "Feature flags, release conditions, early access features.",
    "analytics": "Product analytics, funnels, retention, and user behavior analysis - insights",
    "session_replay": "Session recordings, privacy controls, and replay analysis",
    "toolbar": "PostHog toolbar, heatmaps",
    "surveys": "User feedback collection, survey creation, and response analysis",
    "web_analytics": "Website analytics including web vitals, traffic/session analysis, and conversion tracking",
    "error_tracking": "Error and exception capture and monitoring. Do not use this for errors in the PostHog app!",
    "cdp_destinations": "Customer Data Platform destinations and data forwarding",
    "data_ingestion": "Event capture, SDKs, and data pipeline issues",
    "batch_exports": "Data exports, scheduled exports, and external data delivery",
    "workflows": "Automation, triggers, and workflow configuration",
    "platform_addons": "Additional platform features and premium add-ons",
    "max-ai": "PostHog AI assistant, Max, and AI-powered features",
    "customer-analytics": "Customer journey analysis, lifecycle tracking, and revenue analytics",
}


class CreateSupportTicketToolArgs(BaseModel):
    summary: str = Field(
        description="A clear, concise summary written on behalf of the user, describing their main issue or question (3-4 sentences max)"
    )
    # NOTE: These values must match SupportTicketTargetArea in frontend/src/lib/components/Support/supportLogic.ts
    # If you update this list, also update the frontend type definition
    # also keep in sync with the descriptions in TARGET_AREA_DESCRIPTIONS
    target_area: Literal[
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
        description=f"The most appropriate target area for this ticket based on the user's issue. Choose from: {', '.join(f'{k} ({v})' for k, v in TARGET_AREA_DESCRIPTIONS.items())}",
        default="max-ai",
    )
    # NOTE: These values must match SupportTicketSeverityLevel keys in frontend/src/lib/components/Support/supportLogic.ts
    # If you update this list, also update SEVERITY_LEVEL_TO_NAME in the frontend
    priority: Literal["low", "medium", "high", "critical"] = Field(
        description="Priority level based on the severity of the issue", default="medium"
    )


class CreateSupportTicketTool(MaxTool):
    name: str = "create_support_ticket"
    description: str = SUPPORT_ESCALATION_PROMPT
    args_schema: type[BaseModel] = CreateSupportTicketToolArgs

    async def _arun_impl(
        self, summary: str, target_area: str = "max-ai", priority: str = "medium"
    ) -> tuple[str, DraftSupportTicketToolOutput]:
        ui_payload = DraftSupportTicketToolOutput(
            summary=summary,
            target_area=target_area,
            priority=priority,
        )

        return (
            "Here's a draft support ticket with a summary of your conversation. You can review and submit it below:",
            ui_payload,
        )
