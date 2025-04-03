from abc import abstractmethod
from typing import Literal, Any
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
from ee.hogai.graph.root.prompts import ROOT_INSIGHT_DESCRIPTION_PROMPT
from posthog.schema import (
    AssistantContextualTool,
)
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
CONTEXTUAL_TOOL_NAME_TO_TOOL_CONTEXT_PROMPT: dict[AssistantContextualTool, str] = {}


class MaxTool(BaseTool):
    response_format: Literal["content_and_artifact"] = "content_and_artifact"

    thinking_message: str

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
        self._context = config["configurable"]["contextual_tools"].get(self.get_name(), {})
        return self._run_impl(*args, **kwargs)

    @property
    def context(self) -> dict:
        if not hasattr(self, "_context"):
            raise AttributeError("Tool has not been run yet")
        return self._context
