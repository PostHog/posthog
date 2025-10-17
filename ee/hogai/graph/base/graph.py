from collections.abc import Callable, Coroutine
from typing import Any, Generic, Literal, Protocol, runtime_checkable

from langgraph.graph.state import CompiledStateGraph, StateGraph

from posthog.schema import ReasoningMessage

from posthog.models import Team, User

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.utils.types import AssistantNodeName, StateType
from ee.hogai.utils.types.base import BaseState
from ee.hogai.utils.types.composed import MaxNodeName

# Base checkpointer for all graphs
global_checkpointer = DjangoCheckpointer()


# Type alias for async reasoning message function, takes a state and an optional default message content and returns an optional reasoning message
GetReasoningMessageAfunc = Callable[[BaseState, str | None], Coroutine[Any, Any, ReasoningMessage | None]]
GetReasoningMessageMapType = dict[MaxNodeName, GetReasoningMessageAfunc]


# Protocol to check if a node has a reasoning message function at runtime
@runtime_checkable
class HasReasoningMessage(Protocol):
    get_reasoning_message: GetReasoningMessageAfunc


class AssistantCompiledStateGraph(CompiledStateGraph):
    """Wrapper around CompiledStateGraph that preserves reasoning message information.

    Note: This uses __dict__ copying as a workaround since CompiledStateGraph
    doesn't support standard inheritance. This is brittle and may break with
    library updates.
    """

    def __init__(
        self, compiled_graph: CompiledStateGraph, aget_reasoning_message_by_node_name: GetReasoningMessageMapType
    ):
        # Copy the internal state from the compiled graph without calling super().__init__
        # This is a workaround since CompiledStateGraph doesn't support standard inheritance
        self.__dict__.update(compiled_graph.__dict__)
        self.aget_reasoning_message_by_node_name = aget_reasoning_message_by_node_name


class BaseAssistantGraph(Generic[StateType]):
    _team: Team
    _user: User
    _graph: StateGraph
    aget_reasoning_message_by_node_name: GetReasoningMessageMapType

    def __init__(self, team: Team, user: User, state_type: type[StateType]):
        self._team = team
        self._user = user
        self._graph = StateGraph(state_type)
        self._has_start_node = False
        self.aget_reasoning_message_by_node_name = {}

    def add_edge(self, from_node: MaxNodeName, to_node: MaxNodeName):
        if from_node == AssistantNodeName.START:
            self._has_start_node = True
        self._graph.add_edge(from_node, to_node)
        return self

    def add_node(self, node: MaxNodeName, action: Any):
        self._graph.add_node(node, action)
        if isinstance(action, HasReasoningMessage):
            self.aget_reasoning_message_by_node_name[node] = action.get_reasoning_message
        return self

    def add_subgraph(self, node_name: MaxNodeName, subgraph: AssistantCompiledStateGraph):
        self._graph.add_node(node_name, subgraph)
        self.aget_reasoning_message_by_node_name.update(subgraph.aget_reasoning_message_by_node_name)
        return self

    def compile(self, checkpointer: DjangoCheckpointer | None | Literal[False] = None):
        if not self._has_start_node:
            raise ValueError("Start node not added to the graph")
        # TRICKY: We check `is not None` because False has a special meaning of "no checkpointer", which we want to pass on
        compiled_graph = self._graph.compile(
            checkpointer=checkpointer if checkpointer is not None else global_checkpointer
        )
        return AssistantCompiledStateGraph(
            compiled_graph, aget_reasoning_message_by_node_name=self.aget_reasoning_message_by_node_name
        )
