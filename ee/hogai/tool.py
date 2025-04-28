from abc import abstractmethod
import json
from typing import Literal, Any
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
from ee.hogai.graph.root.prompts import ROOT_INSIGHT_DESCRIPTION_PROMPT
from posthog.schema import AssistantContextualTool
from langchain_core.runnables import RunnableConfig

MaxSupportedQueryKind = Literal["trends", "funnel", "retention", "sql"]


# Lower casing matters here. Do not change it.
class create_and_query_insight(BaseModel):
    """
    Retrieve results for a specific data question by creating a query or iterate on a previous query.
    This tool only retrieves data for a single insight at a time.
    The `trends` insight type is the only insight that can display multiple trends insights in one request.
    All other insight types strictly return data for a single insight.
    This tool is also relevant if the user asks to write SQL.
    """

    query_description: str = Field(description="The description of the query being asked.")
    query_kind: MaxSupportedQueryKind = Field(description=ROOT_INSIGHT_DESCRIPTION_PROMPT)


class search_documentation(BaseModel):
    """
    Search PostHog documentation to answer questions about features, concepts, and usage.
    Use this tool when the user asks about how to use PostHog, its features, or needs help understanding concepts.
    Don't use this tool if the necessary information is already in the conversation.
    """


CONTEXTUAL_TOOL_NAME_TO_TOOL: dict[AssistantContextualTool, type["MaxTool"]] = {}


class MaxTool(BaseTool):
    # LangChain's default is just "content", but we always want to return the tool call artifact too
    # - it becomes the `ui_payload`
    response_format: Literal["content_and_artifact"] = "content_and_artifact"

    thinking_message: str
    """The message shown to let the user know this tool is being used. One sentence, no punctuation.
    For example, "Updating filters"
    """
    root_system_prompt_template: str = "No context provided for this tool."
    """The template for context associated with this tool, that will be injected into the root node's system prompt.
    This helps the root node decide _when_ and _whether_ to use the tool.
    It will be formatted like an f-string, with the tool context as the variables.
    For example, "The current filters the user is seeing are: {current_filters}."
    """

    _context: dict[str, Any]
    _team_id: int | None

    @abstractmethod
    def _run_impl(self, *args, **kwargs) -> tuple[str, Any]:
        """Tool execution, which should return a tuple of (content, artifact)"""
        pass

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.__name__.endswith("Tool"):
            raise ValueError("The name of a MaxTool subclass must end with 'Tool', for clarity")
        try:
            accepted_name = AssistantContextualTool(cls.name)
        except ValueError:
            raise ValueError(
                f"MaxTool name '{cls.name}' is not a recognized AssistantContextualTool value. Fix this name, or update AssistantContextualTool in schema-assistant-messages.ts and run `pnpm schema:build`"
            )
        CONTEXTUAL_TOOL_NAME_TO_TOOL[accepted_name] = cls
        if not getattr(cls, "thinking_message", None):
            raise ValueError("You must set `thinking_message` on the tool, so that we can show the tool kicking off")

    def _run(self, *args, config: RunnableConfig, **kwargs):
        self._context = config["configurable"].get("contextual_tools", {}).get(self.get_name(), {})
        self._team_id = config["configurable"].get("team_id", None)
        return self._run_impl(*args, **kwargs)

    @property
    def context(self) -> dict:
        if not hasattr(self, "_context"):
            raise AttributeError("Tool has not been run yet")
        return self._context

    def format_system_prompt_injection(self, context: dict[str, Any]) -> str:
        formatted_context = {
            key: (json.dumps(value) if isinstance(value, dict | list) else value) for key, value in context.items()
        }
        return self.root_system_prompt_template.format(**formatted_context)
