from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, ValidationError

from posthog.schema import AgentMode

from posthog.models import Team, User

from ee.hogai.utils.types.base import NodePath

if TYPE_CHECKING:
    from .nodes import AgentExecutable, AgentToolsExecutable


class AgentModeValidator(BaseModel):
    mode: AgentMode


def validate_mode(mode: Any) -> AgentMode | None:
    try:
        return AgentModeValidator(mode=mode).mode
    except ValidationError:
        return None


class AgentModeManager:
    _node: Optional["AgentExecutable"] = None
    _tools_node: Optional["AgentToolsExecutable"] = None

    def __init__(self, *, team: Team, user: User, node_path: tuple[NodePath, ...], mode: AgentMode | None = None):
        self._team = team
        self._user = user
        self._node_path = node_path
        self._mode = mode or AgentMode.PRODUCT_ANALYTICS

    @property
    def node(self) -> "AgentExecutable":
        if not self._node:
            from ee.hogai.mode_registry import MODE_REGISTRY

            agent_definition = MODE_REGISTRY[self._mode]
            self._node = agent_definition.node_class(
                team=self._team,
                user=self._user,
                node_path=self._node_path,
                toolkit_class=agent_definition.toolkit_class,
            )
        return self._node

    @property
    def tools_node(self) -> "AgentToolsExecutable":
        if not self._tools_node:
            from ee.hogai.mode_registry import MODE_REGISTRY

            agent_definition = MODE_REGISTRY[self._mode]
            self._tools_node = agent_definition.tools_node_class(
                team=self._team,
                user=self._user,
                node_path=self._node_path,
                toolkit_class=agent_definition.toolkit_class,
            )
        return self._tools_node

    @property
    def mode(self) -> AgentMode:
        return self._mode

    @mode.setter
    def mode(self, value: AgentMode):
        self._mode = value
        self._node = None
        self._tools_node = None
