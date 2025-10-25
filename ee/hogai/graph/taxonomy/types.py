from enum import Enum, StrEnum
from typing import Generic, Optional, TypeVar

from langchain_core.messages import BaseMessage as LangchainBaseMessage
from langgraph.graph import END, START
from pydantic import BaseModel, Field

from ee.hogai.utils.types.base import BaseStateWithIntermediateSteps, BaseStateWithMessages

OutputType = TypeVar("OutputType", bound=BaseModel)


class TaxonomyAgentState(BaseStateWithIntermediateSteps, BaseStateWithMessages, Generic[OutputType]):
    """
    Partial state class for filter options functionality.
    Only includes fields relevant to filter options generation.
    """

    output: Optional[OutputType | str] = Field(default=None)
    """
    The output of the taxonomy agent.
    """

    change: Optional[str] = Field(default=None)
    """
    The change requested for the filters.
    """

    instructions: Optional[str] = Field(default=None)
    """
    The instructions for the taxonomy agent.
    """

    tool_progress_messages: list[LangchainBaseMessage] = Field(default=[])
    """
    The messages with tool calls to collect tool progress.
    """

    iteration_count: int | None = Field(default=None)
    """
    The number of iterations the taxonomy agent has gone through.
    """


class TaxonomyNodeName(StrEnum):
    """Generic node names for taxonomy agents."""

    LOOP_NODE = "taxonomy_loop_node"
    TOOLS_NODE = "taxonomy_tools_node"
    START = START
    END = END
    TASK_EXECUTOR = "taxonomy_task_executor"


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
