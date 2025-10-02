from typing import Any, Literal

from django.conf import settings

from pydantic import BaseModel, Field

from ee.hogai.tool import MaxTool

SEARCH_TOOL_PROMPT = """
Use this tool to search docs or insights by using natural language.

# Documentation search

This tool is absolutely NECESSARY to answer PostHog-related questions accurately, as our product and docs change all the time:
- How to use PostHog
- How to use PostHog features
- How to contact support or other humans
- How to report bugs
- How to submit feature requests
- To troubleshoot something
- What default fields and properties are available for events and persons
- …Or anything else PostHog-related

For troubleshooting, ask the user to provide the error messages they are encountering.
If no error message is involved, ask the user to describe their expected results vs. the actual results they're seeing.
You avoid suggesting things that the user has told you they've already tried.

Examples:
- Needs help understanding PostHog concepts
- Has questions about SDK integration or instrumentation
    - e.g. `posthog.capture('event')`, `posthog.captureException(err)`,
    `posthog.identify(userId)`, `capture({ ... })` not working, etc.
- Troubleshooting missing or unexpected data
    - e.g. "Events aren't arriving", "Why don't I see errors on the dashboard?"
- Wants to know more about PostHog the company
- Has questions about incidents or system status
- Has disabled session replay and needs help turning it back on
- Reports an issue with PostHog

If the user's question should be satisfied by using insights, do that before answering using documentation.

# Insights search

Use this tool when you can assume that an insight you want to analyze was already created by the user.

Examples:
- Product-specific metrics that most likely exist.
- Common sense metrics that are relevant to the product.
""".strip()


SearchKind = Literal["insights"] | Literal["docs"]


class SearchToolArgs(BaseModel):
    kind: SearchKind = Field(description="Select the entity you want to find")
    query: str = Field(
        description="Describe what you want to find. Include as much details from the context as possible."
    )


class SearchTool(MaxTool):
    name: Literal["search"] = "search"
    description: str = SEARCH_TOOL_PROMPT
    thinking_message: str = "Searching for information"
    root_system_prompt_template: str = "Searches documentation or user data in PostHog (insights)"
    args_schema: type[BaseModel] = SearchToolArgs
    show_tool_call_message: bool = False

    async def _arun_impl(self, kind: SearchKind, query: str) -> tuple[str, dict[str, Any] | None]:
        if kind == "docs" and not settings.INKEEP_API_KEY:
            return "This tool is not available in this environment.", None
        # Used for routing
        return "Search tool executed", SearchToolArgs(kind=kind, query=query).model_dump()
