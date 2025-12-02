import asyncio
from collections.abc import Awaitable, Sequence
from typing import TYPE_CHECKING, ClassVar, TypeVar, cast

import structlog
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    AgentMode,
    AssistantMessage,
    AssistantToolCallMessage,
    ContextMessage,
    FailureMessage,
    HumanMessage,
)

from posthog.models import Team, User

from ee.hogai.context import AssistantContextManager
from ee.hogai.tools.switch_mode import SwitchModeTool
from ee.hogai.tools.todo_write import TodoWriteTool
from ee.hogai.utils.types.base import AssistantState

if TYPE_CHECKING:
    from ee.hogai.tool import MaxTool
    from ee.hogai.tools.todo_write import TodoWriteExample

    from .factory import AgentModeDefinition


RootMessageUnion = HumanMessage | AssistantMessage | FailureMessage | AssistantToolCallMessage | ContextMessage
T = TypeVar("T", RootMessageUnion, BaseMessage)


logger = structlog.get_logger(__name__)


class AgentToolkit:
    POSITIVE_TODO_EXAMPLES: ClassVar[Sequence["TodoWriteExample"] | None] = None
    """
    Positive examples that will be injected into the `todo_write` tool. Use this field to explain the agent how it should orchestrate complex tasks using provided tools.
    """
    NEGATIVE_TODO_EXAMPLES: ClassVar[Sequence["TodoWriteExample"] | None] = None
    """
    Negative examples that will be injected into the `todo_write` tool. Use this field to explain the agent how it should **NOT** orchestrate tasks using provided tools.
    """

    def __init__(
        self,
        *,
        team: Team,
        user: User,
        context_manager: AssistantContextManager,
    ):
        """
        Initialize the agent toolkit.

        Args:
            team: The team to use for the agent.
            user: The user to use for the agent.
            context_manager: The context manager to use for the agent.
        """
        self._team = team
        self._user = user
        self._context_manager = context_manager

    @property
    def tools(self) -> list[type["MaxTool"]]:
        """
        Custom tools are tools that are not part of the default toolkit.
        """
        return []


class AgentToolkitManager:
    _mode_registry: dict[AgentMode, "AgentModeDefinition"]
    _agent_toolkit: type[AgentToolkit]
    _mode_toolkit: type[AgentToolkit]

    def __init__(self, *, team: Team, user: User, context_manager: AssistantContextManager):
        self._team = team
        self._user = user
        self._context_manager = context_manager

    @classmethod
    def configure(
        cls,
        agent_toolkit: type[AgentToolkit],
        mode_toolkit: type[AgentToolkit],
        mode_registry: dict[AgentMode, "AgentModeDefinition"],
    ):
        cls._agent_toolkit = agent_toolkit
        cls._mode_toolkit = mode_toolkit
        cls._mode_registry = mode_registry

    async def get_tools(self, state: AssistantState, config: RunnableConfig) -> list["MaxTool"]:
        # Processed tools
        available_tools: list[MaxTool] = []

        # Initialize the static toolkit
        static_tools: list[Awaitable[MaxTool]] = []
        for toolkit_class in [self._agent_toolkit, self._mode_toolkit]:
            toolkit = toolkit_class(team=self._team, user=self._user, context_manager=self._context_manager)
            for tool_class in toolkit.tools:
                if tool_class is TodoWriteTool:
                    if toolkit_class is self._mode_toolkit:
                        raise ValueError("TodoWriteTool is not allowed in the mode toolkit")
                    todo_future = cast(type[TodoWriteTool], tool_class).create_tool_class(
                        team=self._team,
                        user=self._user,
                        state=state,
                        config=config,
                        context_manager=self._context_manager,
                        positive_examples=toolkit.POSITIVE_TODO_EXAMPLES,
                        negative_examples=toolkit.NEGATIVE_TODO_EXAMPLES,
                    )
                    static_tools.append(todo_future)
                elif tool_class == SwitchModeTool:
                    if toolkit_class is self._mode_toolkit:
                        raise ValueError("SwitchModeTool is not allowed in the mode toolkit")
                    switch_mode_future = SwitchModeTool.create_tool_class(
                        team=self._team,
                        user=self._user,
                        state=state,
                        config=config,
                        context_manager=self._context_manager,
                        mode_registry=self._mode_registry,
                        default_tool_classes=toolkit.tools,
                    )
                    static_tools.append(switch_mode_future)
                else:
                    tool_future = tool_class.create_tool_class(
                        team=self._team,
                        user=self._user,
                        state=state,
                        config=config,
                        context_manager=self._context_manager,
                    )
                    static_tools.append(tool_future)
        available_tools.extend(await asyncio.gather(*static_tools))

        return available_tools
