from typing import Any

from pydantic import BaseModel, Field

from posthog.schema import AssistantNavigateUrl

from ee.hogai.tool import MaxTool

NAVIGATION_TOOL_PROMPT = """
Use the `navigate` tool to move between different pages in the PostHog application.
These pages are tied to PostHog's products and/or functionalities and provide tools for retrieving information or performing actions.
After navigating to a page, you can use the tools available there to retrieve information or perform actions.

General rules for navigation:
- If you don't have tools available for a specific functionality, navigate to the relevant product page to get access to its tools.
- If a user asks to do something fun in the platform you can navigate them to the `game368hedgehogs` page.
""".strip()


class NavigateToolArgs(BaseModel):
    page_key: AssistantNavigateUrl = Field(
        description="The specific key identifying the page to navigate to. Must be one of the predefined literal values."
    )


class NavigateTool(MaxTool):
    name: str = "navigate"
    description: str = NAVIGATION_TOOL_PROMPT
    root_system_prompt_template: str = (
        "You're currently on the {current_page} page. "
        "You can navigate around the PostHog app using the 'navigate' tool.\n\n"
        "Some of the pages in the app have helpful descriptions. Some have tools that you can use only there. See the following list:\n"
        "{scene_descriptions}\n"
        "After navigating to a new page, you'll have access to that page's specific tools."
    )
    thinking_message: str = "Navigating"
    args_schema: type[BaseModel] = NavigateToolArgs

    def _run_impl(self, page_key: AssistantNavigateUrl) -> tuple[str, Any]:
        # Note that page_key should get replaced by a nicer breadcrumbs-based name in the frontend
        # but it's useful for the LLM to still have the page_key in chat history
        return f"Navigated to **{page_key}**.", {"page_key": page_key}
