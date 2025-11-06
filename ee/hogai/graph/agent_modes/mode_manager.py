from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, ValidationError

from posthog.schema import AgentMode

from posthog.models import Team, User

from .presets import MODE_REGISTRY

if TYPE_CHECKING:
    from .nodes import AgentNode, AgentToolsNode


class AgentModeValidator(BaseModel):
    mode: AgentMode


def validate_mode(mode: Any) -> AgentMode | None:
    try:
        return AgentModeValidator(mode=mode).mode
    except ValidationError:
        return None


class AgentModeManager:
    __node: Optional["AgentNode"] = None
    __tools_node: Optional["AgentToolsNode"] = None

    def __init__(self, team: Team, user: User, mode: AgentMode | None = None):
        self._team = team
        self._user = user
        self._mode = mode or AgentMode.PRODUCT_ANALYTICS

    @property
    def node(self) -> "AgentNode":
        if not self.__node:
            agent_definition = MODE_REGISTRY[self._mode]
            self.__node = agent_definition.node_class(
                self._team, self._user, toolkit_class=agent_definition.toolkit_class
            )
        return self.__node

    @property
    def tools_node(self) -> "AgentToolsNode":
        if not self.__tools_node:
            agent_definition = MODE_REGISTRY[self._mode]
            self.__tools_node = agent_definition.tools_node_class(
                self._team, self._user, toolkit_class=agent_definition.toolkit_class
            )
        return self.__tools_node

    @property
    def mode(self) -> AgentMode:
        return self._mode

    @mode.setter
    def mode(self, value: AgentMode):
        self._mode = value
        self.__node = None
        self.__tools_node = None
