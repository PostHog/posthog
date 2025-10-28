from posthog.schema import AgentMode

from posthog.models import Team, User

from .nodes import AgentNode, AgentToolsNode


class AgentModeManager:
    def __init__(self, team: Team, user: User, mode: AgentMode = AgentMode.PRODUCT_ANALYTICS):
        self._team = team
        self._user = user
        self._mode = mode

    @property
    def node(self, mode: AgentMode) -> AgentNode:
        if not self.__node:
            from ee.hogai.mode_registry import MODE_REGISTRY

            agent_definition = MODE_REGISTRY[mode]
            self.__node = agent_definition.node_class(
                self._team, self._user, toolkit_class=agent_definition.toolkit_class
            )
        return self.__node

    @property
    def tools_node(self, mode: AgentMode) -> AgentToolsNode:
        if not self.__tools_node:
            from ee.hogai.mode_registry import MODE_REGISTRY

            agent_definition = MODE_REGISTRY[mode]
            self.__tools_node = agent_definition.tools_node_class(
                self._team, self._user, toolkit_class=agent_definition.toolkit_class
            )
        return self.__tools_node
