import asyncio
from typing import Literal, Self

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, create_model

from posthog.models import Team, User

from ee.hogai.context import AssistantContextManager
from ee.hogai.tool import MaxTool
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import AssistantState, NodePath

SWITCH_MODE_PROMPT = """
Use this tool to switch yourself to a different mode (implementation) that provides different specialized capabilities and tools.
Switching the mode will preserve your current conversation history and context.

# Default tools
The tools below are always available across all modes:
{{{default_tools}}}

# Available modes and corresponding tools
{{{available_modes}}}

When to use this tool:
- You need a tool or capability.
- You need a specialized knowledge.

When NOT to use this tool:
- You already have all necessary tools and capabilities in the current mode.
""".strip()

SWITCH_MODE_TOOL_PROMPT = """
Switched to mode {{{new_mode}}}.
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
                    for tool_class in definition.toolkit_class(team, user, context_manager).custom_tools
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
    from ee.hogai.graph.agent.nodes import DEFAULT_TOOLS

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
    thinking_message: str = "Switching to a different mode"
    context_prompt_template: str = "N/A"  # TODO:

    async def _arun_impl(self, new_mode: str) -> tuple[str, str]:
        return format_prompt_string(SWITCH_MODE_TOOL_PROMPT, new_mode=new_mode), new_mode

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
