from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import AgentMode

from posthog.models import Team, User

from ee.hogai.context import AssistantContextManager
from ee.hogai.core.agent_modes.factory import AgentModeDefinition
from ee.hogai.core.agent_modes.mode_manager import AgentModeManager
from ee.hogai.core.agent_modes.prompt_builder import AgentPromptBuilder
from ee.hogai.core.agent_modes.toolkit import AgentToolkit, AgentToolkitManager
from ee.hogai.core.mixins import AssistantContextMixin
from ee.hogai.synthetic_user.preset import synthetic_user_agent
from ee.hogai.utils.types.base import AssistantState, NodePath

SYNTHETIC_USER_PROMPT = """
You are a synthetic user navigating a website. You are given a task to complete and a persona to pretend to be.

You should think like this person.
Your goal is to mimic how this person would behave and complete the task.

At the end of the task, you should return the results using the task_result tool.
"""


class SyntheticUserPromptBuilder(AgentPromptBuilder, AssistantContextMixin):
    async def get_prompts(self, state: AssistantState, config: RunnableConfig) -> list[BaseMessage]:
        return ChatPromptTemplate.from_messages(
            [
                ("system", SYNTHETIC_USER_PROMPT),
            ],
            template_format="mustache",
        ).format_messages()


class SyntheticUserModeManager(AgentModeManager):
    def __init__(
        self,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...],
        context_manager: AssistantContextManager,
        state: AssistantState,
    ):
        super().__init__(team=team, user=user, node_path=node_path, context_manager=context_manager, state=state)
        self._mode = AgentMode.BROWSER_USE

    @property
    def mode_registry(self) -> dict[AgentMode, AgentModeDefinition]:
        return {AgentMode.BROWSER_USE: synthetic_user_agent}

    @property
    def prompt_builder_class(self) -> type[AgentPromptBuilder]:
        return SyntheticUserPromptBuilder

    @property
    def toolkit_class(self) -> type[AgentToolkit]:
        return AgentToolkit

    @property
    def toolkit_manager_class(self) -> type[AgentToolkitManager]:
        return AgentToolkitManager
