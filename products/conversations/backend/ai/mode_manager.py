from typing import TYPE_CHECKING

from posthog.schema import AgentMode

from posthog.models import Team, User

from products.conversations.backend.ai.prompt_builder import SupportAgentPromptBuilder

from ee.hogai.context import AssistantContextManager
from ee.hogai.core.agent_modes.factory import AgentModeDefinition
from ee.hogai.core.agent_modes.mode_manager import AgentModeManager
from ee.hogai.core.agent_modes.prompt_builder import AgentPromptBuilder
from ee.hogai.core.agent_modes.toolkit import AgentToolkit, AgentToolkitManager
from ee.hogai.tools import ExecuteSQLTool, ReadDataTool, ReadTaxonomyTool, SearchTool
from ee.hogai.utils.types.base import AssistantState, NodePath

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool


class SupportAgentToolkit(AgentToolkit):
    """Focused toolkit for the support agent -- no mode switching, no todos, no notebooks."""

    @property
    def tools(self) -> list[type["MaxTool"]]:
        return [ReadTaxonomyTool, ReadDataTool, SearchTool, ExecuteSQLTool]


SUPPORT_MODE = AgentModeDefinition(
    mode=AgentMode.PRODUCT_ANALYTICS,
    mode_description="Support agent mode",
    # AgentToolkitManager merges agent toolkit + mode toolkit; tools live on the
    # agent toolkit (SupportAgentToolkit) so the mode toolkit must be empty to
    # avoid duplicate tool names sent to the LLM.
    toolkit_class=AgentToolkit,
)


class SupportAgentModeManager(AgentModeManager):
    """Single-mode manager for the support agent. No mode switching."""

    def __init__(
        self,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...],
        context_manager: AssistantContextManager,
        state: AssistantState,
    ):
        self._mode = AgentMode.PRODUCT_ANALYTICS
        super().__init__(
            team=team,
            user=user,
            node_path=node_path,
            context_manager=context_manager,
            state=state,
        )

    @property
    def mode_registry(self) -> dict[AgentMode, AgentModeDefinition]:
        return {AgentMode.PRODUCT_ANALYTICS: SUPPORT_MODE}

    @property
    def toolkit_class(self) -> type[AgentToolkit]:
        return SupportAgentToolkit

    @property
    def prompt_builder_class(self) -> type[AgentPromptBuilder]:
        return SupportAgentPromptBuilder

    @property
    def toolkit_manager_class(self) -> type[AgentToolkitManager]:
        return AgentToolkitManager
