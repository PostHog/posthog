from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

from posthog.schema import AgentMode

from posthog.models import Team, User

from ee.hogai.context import AssistantContextManager
from ee.hogai.core.agent_modes.prompt_builder import AgentPromptBuilder
from ee.hogai.core.agent_modes.toolkit import AgentToolkit, AgentToolkitManager
from ee.hogai.core.mixins import AssistantContextMixin
from ee.hogai.utils.types.base import NodePath

if TYPE_CHECKING:
    from .executables import AgentExecutable, AgentToolsExecutable
    from .factory import AgentModeDefinition


class AgentModeManager(AssistantContextMixin, ABC):
    _node: Optional["AgentExecutable"] = None
    _tools_node: Optional["AgentToolsExecutable"] = None

    def __init__(
        self,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...],
        context_manager: AssistantContextManager,
        mode: AgentMode | None = None,
    ):
        self._team = team
        self._user = user
        self._node_path = node_path
        self._context_manager = context_manager
        self._mode = mode or AgentMode.PRODUCT_ANALYTICS

    @property
    @abstractmethod
    def mode_registry(self) -> dict[AgentMode, "AgentModeDefinition"]:
        raise NotImplementedError("Mode registry is not implemented")

    @property
    @abstractmethod
    def toolkit_class(self) -> type[AgentToolkit]:
        raise NotImplementedError("Toolkit classes are not implemented")

    @property
    @abstractmethod
    def prompt_builder_class(self) -> type[AgentPromptBuilder]:
        raise NotImplementedError("Prompt builder class is not implemented")

    @property
    @abstractmethod
    def toolkit_manager_class(self) -> type[AgentToolkitManager]:
        return AgentToolkitManager

    @property
    def node(self) -> "AgentExecutable":
        if not self._node:
            agent_definition = self.mode_registry[self._mode]
            toolkit_manager_class = self.toolkit_manager_class
            toolkit_manager_class.configure(
                agent_toolkit=self.toolkit_class,
                mode_toolkit=agent_definition.toolkit_class,
                mode_registry=self.mode_registry,
            )
            self._node = agent_definition.node_class(
                team=self._team,
                user=self._user,
                node_path=self._node_path,
                toolkit_manager_class=toolkit_manager_class,
                prompt_builder_class=self.prompt_builder_class,
            )
        return self._node

    @property
    def tools_node(self) -> "AgentToolsExecutable":
        if not self._tools_node:
            agent_definition = self.mode_registry[self._mode]
            toolkit_manager_class = self.toolkit_manager_class
            toolkit_manager_class.configure(
                agent_toolkit=self.toolkit_class,
                mode_toolkit=agent_definition.toolkit_class,
                mode_registry=self.mode_registry,
            )
            self._tools_node = agent_definition.tools_node_class(
                team=self._team,
                user=self._user,
                node_path=self._node_path,
                toolkit_manager_class=toolkit_manager_class,
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
