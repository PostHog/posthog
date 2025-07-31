from typing import Generic, Optional, TypeVar
from pydantic import BaseModel

from langchain_core.agents import AgentAction
from langchain_core.messages import BaseMessage as LangchainBaseMessage
from pydantic import Field

from ee.hogai.utils.types import BaseState

T = TypeVar("T", bound=BaseModel)


class PartialTaxonomyAgentState(Generic[T], BaseState):
    """
    Partial state class for filter options functionality.
    Only includes fields relevant to filter options generation.
    """

    intermediate_steps: Optional[list[tuple[AgentAction, Optional[str]]]] = Field(default=None)
    """
    Actions taken by the ReAct agent.
    """

    output: Optional[T] = Field(default=None)
    """
    The output of the taxonomy agent.
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


class TaxonomyAgentState(PartialTaxonomyAgentState):
    """
    State class specifically for filter options functionality.
    Only includes fields relevant to filter options generation.
    """

    pass
