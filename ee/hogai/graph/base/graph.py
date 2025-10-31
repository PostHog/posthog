from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generic, Literal

from langgraph.graph.state import StateGraph

from posthog.models import Team, User

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.utils.types.base import AssistantGraphName, AssistantNodeName, NodePath, PartialStateType, StateType

from .node import BaseAssistantNode

if TYPE_CHECKING:
    from ee.hogai.utils.types.composed import MaxNodeName


# Base checkpointer for all graphs
global_checkpointer = DjangoCheckpointer()


class BaseAssistantGraph(Generic[StateType, PartialStateType], ABC):
    _team: Team
    _user: User
    _graph: StateGraph
    _node_path: tuple[NodePath, ...]

    def __init__(
        self,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...],
    ):
        self._team = team
        self._user = user
        self._graph = StateGraph(self.state_type)
        self._has_start_node = False
        self._node_path = (*node_path, NodePath(name=self.graph_name.value))

    @property
    @abstractmethod
    def state_type(self) -> type[StateType]: ...

    @property
    @abstractmethod
    def graph_name(self) -> AssistantGraphName: ...

    def add_edge(self, from_node: "MaxNodeName", to_node: "MaxNodeName"):
        if from_node == AssistantNodeName.START:
            self._has_start_node = True
        self._graph.add_edge(from_node, to_node)
        return self

    def add_node(self, node: "MaxNodeName", action: BaseAssistantNode[StateType, PartialStateType]):
        self._graph.add_node(node, action)
        return self

    def compile(self, checkpointer: DjangoCheckpointer | None | Literal[False] = None):
        if not self._has_start_node:
            raise ValueError("Start node not added to the graph")
        # TRICKY: We check `is not None` because False has a special meaning of "no checkpointer", which we want to pass on
        compiled_graph = self._graph.compile(
            checkpointer=checkpointer if checkpointer is not None else global_checkpointer
        )
        return compiled_graph
