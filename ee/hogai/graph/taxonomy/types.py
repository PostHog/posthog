from enum import StrEnum, Enum
from langgraph.graph import END, START
from pydantic import BaseModel
from typing import TypeVar


from langchain_core.agents import AgentAction
from langchain_core.messages import BaseMessage as LangchainBaseMessage
from pydantic import Field
from typing import Generic, Optional
from ee.hogai.utils.types import BaseState

# Type variables for the new generic classes
ToolInputType = TypeVar("ToolInputType", bound=BaseModel)
OutputType = TypeVar("OutputType", bound=BaseModel)


class PartialTaxonomyAgentState(BaseState, Generic[OutputType]):
    """
    Partial state class for filter options functionality.
    Only includes fields relevant to filter options generation.
    """

    intermediate_steps: Optional[list[tuple[AgentAction, Optional[str]]]] = Field(default=None)
    """
    Actions taken by the ReAct agent.
    """

    output: Optional[OutputType] = Field(default=None)
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


class TaxonomyAgentState(PartialTaxonomyAgentState[OutputType]):
    """
    State class specifically for filter options functionality.
    Only includes fields relevant to filter options generation.
    """


class TaxonomyNodeName(StrEnum):
    """Generic node names for taxonomy agents."""

    LOOP_NODE = "taxonomy_loop_node"
    TOOLS_NODE = "taxonomy_tools_node"
    START = START
    END = END


class EntityType(str, Enum):
    """Base entity types for taxonomy agents."""

    PERSON = "person"
    SESSION = "session"
    EVENT = "event"
    ACTION = "action"

    @classmethod
    def values(cls) -> list[str]:
        """Get all entity type values as strings."""
        return [entity.value for entity in cls]
