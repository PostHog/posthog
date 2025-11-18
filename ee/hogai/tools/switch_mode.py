import asyncio
from typing import Literal, Self, cast

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, create_model

from posthog.schema import AgentMode

from posthog.models import Team, User

from ee.hogai.context import AssistantContextManager
from ee.hogai.tool import MaxTool
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import AssistantState, NodePath

SWITCH_MODE_PROMPT = """
Use this tool to switch to a specialized mode with different tools and capabilities. Your conversation history and context are preserved across mode switches.

# Common tools (available in all modes)
{{{default_tools}}}

# Specialized modes
{{{available_modes}}}

Decision framework:
1. Check if you already have the necessary tools in your current mode
2. If not, identify which mode provides the tools you need
3. Switch to that mode using this tool

Switch when:
- You need a tool listed in another mode's toolkit (e.g., execute_sql is only in sql mode)
- The task type clearly maps to a specialized mode (SQL queries → sql mode, trend analysis → product_analytics mode)
- You've confirmed your current mode lacks required capabilities

Do NOT switch when:
- You can complete the task with your current tools
- The task is informational/explanatory (no tools needed)
- You're uncertain–check your current tools first

After switching, you'll have access to that mode's specialized tools while retaining access to all common tools.
""".strip()

SWITCH_MODE_TOOL_PROMPT = """
Successfully switched to {{{new_mode}}} mode. You now have access to this mode's specialized tools.
""".strip()


SWITCH_MODE_FAILURE_PROMPT = """
Failed to switch to {{{new_mode}}} mode. This mode does not exist. Available modes: {{{available_modes}}}.
""".strip()


async def _get_modes_prompt(
    *,
    team: Team,
    user: User,
    state: AssistantState | None = None,
    config: RunnableConfig | None = None,
    context_manager: AssistantContextManager,
) -> str:
    """Get the prompt containing the description of the available modes."""
    from ee.hogai.mode_registry import MODE_REGISTRY

    all_futures: list[asyncio.Future[list[MaxTool]]] = []
    for definition in MODE_REGISTRY.values():
        all_futures.append(
            asyncio.gather(
                *[
                    tool_class.create_tool_class(team=team, user=user, state=state, config=config)
                    for tool_class in definition.toolkit_class(
                        team=team, user=user, context_manager=context_manager
                    ).custom_tools
                ]
            )
        )

    resolved_tools = await asyncio.gather(*all_futures)
    formatted_modes: list[str] = []
    for definition, tools in zip(MODE_REGISTRY.values(), resolved_tools):
        formatted_modes.append(
            f"- {definition.mode.value} – {definition.mode_description}. [Mode tools: {', '.join([tool.get_name() for tool in tools])}]"
        )

    return "\n".join(formatted_modes)


async def _get_default_tools_prompt(
    *,
    team: Team,
    user: User,
    state: AssistantState | None = None,
    config: RunnableConfig | None = None,
) -> str:
    """Get the prompt containing the description of the default tools."""
    from ee.hogai.graph.agent_modes.nodes import DEFAULT_TOOLS

    resolved_tools = await asyncio.gather(
        *[
            tool_class.create_tool_class(team=team, user=user, state=state, config=config)
            for tool_class in DEFAULT_TOOLS
            if tool_class != SwitchModeTool
        ]
    )
    return ", ".join([tool.get_name() for tool in resolved_tools]) + ", switch_mode"


class SwitchModeTool(MaxTool):
    name: Literal["switch_mode"] = "switch_mode"

    async def _arun_impl(self, new_mode: str) -> tuple[str, AgentMode | None]:
        from ee.hogai.mode_registry import MODE_REGISTRY

        if new_mode not in MODE_REGISTRY:
            available = ", ".join(MODE_REGISTRY.keys())
            return (
                format_prompt_string(SWITCH_MODE_FAILURE_PROMPT, new_mode=new_mode, available_modes=available),
                self._state.agent_mode,
            )

        return format_prompt_string(SWITCH_MODE_TOOL_PROMPT, new_mode=new_mode), cast(AgentMode, new_mode)

    @classmethod
    async def create_tool_class(
        cls,
        *,
        team: Team,
        user: User,
        node_path: tuple[NodePath, ...] | None = None,
        state: AssistantState | None = None,
        config: RunnableConfig | None = None,
        context_manager: AssistantContextManager | None = None,
    ) -> Self:
        from ee.hogai.mode_registry import MODE_REGISTRY

        context_manager = AssistantContextManager(team, user, config)
        default_tools, available_modes = await asyncio.gather(
            _get_default_tools_prompt(team=team, user=user, state=state, config=config),
            _get_modes_prompt(team=team, user=user, state=state, config=config, context_manager=context_manager),
        )
        description_prompt = format_prompt_string(
            SWITCH_MODE_PROMPT, default_tools=default_tools, available_modes=available_modes
        )

        ModeKind = Literal[*MODE_REGISTRY.keys()]  # type: ignore
        args_schema = create_model(
            "SwitchModeToolArgs",
            __base__=BaseModel,
            new_mode=(
                ModeKind,
                Field(description="The name of the mode to switch to."),
            ),
        )

        return cls(
            team=team,
            user=user,
            state=state,
            config=config,
            description=description_prompt,
            args_schema=args_schema,
        )
