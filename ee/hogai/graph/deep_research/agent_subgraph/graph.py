from typing import Optional

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.graph import BaseAssistantGraph
from ee.hogai.utils.types import (
    AgentSubgraphState,
    AssistantNodeName,
)
from posthog.models import Team, User
from .nodes import TaskExecutorNode


class AgentSubgraph(BaseAssistantGraph[AgentSubgraphState]):
    """
    Agent Subgraph for executing research tasks.
    """

    def __init__(self, team: Team, user: User):
        super().__init__(team, user, AgentSubgraphState)

    def add_task_executor(self, next_node: AssistantNodeName = AssistantNodeName.END):
        """
        Add the core task executor node that handles task execution.
        """
        executor_node = TaskExecutorNode(self._team, self._user)
        self.add_node(AssistantNodeName.TASK_EXECUTOR, executor_node)
        self.add_edge(AssistantNodeName.TASK_EXECUTOR, next_node)
        return self

    def compile_full_graph(self, checkpointer: Optional[DjangoCheckpointer] = None):
        """
        Compile the complete agent subgraph.

        Creates: START -> task_executor -> END
        """
        return (
            self.add_edge(AssistantNodeName.START, AssistantNodeName.TASK_EXECUTOR)
            .add_task_executor()
            .compile(checkpointer=checkpointer)
        )
