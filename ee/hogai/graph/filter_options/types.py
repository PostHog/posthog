from enum import StrEnum
from typing import Optional

from langchain_core.agents import AgentAction
from langchain_core.messages import BaseMessage as LangchainBaseMessage
from pydantic import Field

from ee.hogai.utils.types import BaseState


class PartialFilterOptionsState(BaseState):
    """
    Partial state class for filter options functionality.
    Only includes fields relevant to filter options generation.
    """

    intermediate_steps: Optional[list[tuple[AgentAction, Optional[str]]]] = Field(default=None)
    """
    Actions taken by the ReAct agent.
    """

    generated_filter_options: Optional[dict] = Field(default=None)
    """
    The filter options to apply to the product.
    """

    change: Optional[str] = Field(default=None)
    """
    The change requested for the filters.
    """

    current_filters: Optional[dict] = Field(default=None)
    """
    The current filters applied to the product.
    """

    tool_progress_messages: list[LangchainBaseMessage] = Field(default=[])
    """
    The messages with tool calls to collect tool progress.
    """


class FilterOptionsState(PartialFilterOptionsState):
    """
    State class specifically for filter options functionality.
    Only includes fields relevant to filter options generation.
    """

    pass


class FilterOptionsNodeName(StrEnum):
    FILTER_OPTIONS = "filter_options"
    FILTER_OPTIONS_TOOLS = "filter_options_tools"
