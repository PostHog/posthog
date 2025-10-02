from pydantic import BaseModel, Field

from posthog.schema import AssistantNavigateUrls, AssistantTool, ToolExecution

from ee.hogai.tool import MaxTool
from ee.hogai.utils.types.base import ToolResult


class NavigateToolArgs(BaseModel):
    page_key: AssistantNavigateUrls = Field(
        description="The specific key identifying the page to navigate to. Must be one of the predefined literal values."
    )


class NavigateTool(MaxTool):
    name: str = AssistantTool.NAVIGATE.value
    description: str = (
        "Navigates to a specified, predefined page or section within the PostHog application using a specific page key. "
        "This tool uses a fixed list of page keys and cannot navigate to arbitrary URLs or pages requiring dynamic IDs not already encoded in the page key. "
        "After navigating, you'll be able to use that page's tools."
        "IMPORTANT: Use this tool by itself. Do not use it in combination with other tools. First navigate, then use the tools on the new page."
    )
    system_prompt_template: str = (
        "You're currently on the {current_page} page. "
        "You can navigate to one of the available pages using the 'navigate' tool. "
        "Some of these pages have tools that you can use to get more information or perform actions. "
        "After navigating to a new page, you'll have access to that page's specific tools."
    )
    args_schema: type[BaseModel] = NavigateToolArgs
    send_result_to_frontend: bool = True

    async def _arun_impl(self, input: ToolExecution) -> ToolResult:
        # Note that page_key should get replaced by a nicer breadcrumbs-based name in the frontend
        # but it's useful for the LLM to still have the page_key in chat history
        page_key = input.args["page_key"]
        return await self._successful_execution(f"Navigated to **{page_key}**.", metadata={"page_key": page_key})
