from products.conversations.backend.ai.mode_manager import SupportAgentModeManager

from ee.hogai.core.loop_graph.graph import AgentLoopGraph
from ee.hogai.utils.types.base import AssistantGraphName


class SupportAgentGraph(AgentLoopGraph):
    @property
    def mode_manager_class(self):
        return SupportAgentModeManager

    @property
    def graph_name(self) -> AssistantGraphName:
        return AssistantGraphName.SUPPORT
