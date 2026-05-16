"""Build per-turn ``<system_reminder>`` content for sandboxed PostHog AI.

Dynamic context — what the user is viewing, their billing state, available
contextual tools, the current mode — is precomputed in Django and prepended to
every user message sent into the sandbox via the agent-server JSON-RPC API.

This is intentionally a slimmer surface than ``AssistantContextManager``: the
LangGraph path operates on ``BaseStateWithMessages`` plus a ``RunnableConfig``;
sandbox conversations only have a per-turn payload. Where the formatting logic
already exists (UI context, contextual tools, mode), we re-use the manager;
where it doesn't (billing summary), we keep a focused renderer here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.utils import timezone as django_timezone

import pytz
import structlog
from langchain_core.runnables import RunnableConfig

from posthog.schema import AgentMode, MaxBillingContext, MaxUIContext

from posthog.models.team.team import Team
from posthog.models.user import User

from ee.hogai.context.context import AssistantContextManager

if TYPE_CHECKING:
    from ee.models.assistant import CoreMemory

logger = structlog.get_logger(__name__)

SYSTEM_REMINDER_OPEN = "<system_reminder>"
SYSTEM_REMINDER_CLOSE = "</system_reminder>"


def _wrap(content: str) -> str:
    """Wrap ``content`` in a single ``<system_reminder>`` block."""
    return f"{SYSTEM_REMINDER_OPEN}\n{content.strip()}\n{SYSTEM_REMINDER_CLOSE}"


def _build_identity_block(user: User, team: Team) -> str:
    project = team.project
    org = team.organization
    tz = pytz.timezone(team.timezone)
    now = django_timezone.now().astimezone(tz)
    lines = [
        f"Project: {project.name} (id={team.project_id})",
        f"Organization: {org.name}",
        f"User: {user.get_full_name()} <{user.email}>",
        f"Project timezone: {team.timezone}",
        f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}",
    ]
    return _wrap("PostHog session context:\n" + "\n".join(lines))


def _build_billing_block(billing: MaxBillingContext) -> str | None:
    """Render a compact summary of the user's billing state.

    Heavy details (per-product spend history, projections) are deliberately
    omitted — the agent can call billing-specific MCP tools when it actually
    needs them. This block is just enough for the agent to know whether the
    user is on a paid plan and whether they're in trial / startup / deactivated
    so suggestions can be calibrated.
    """
    parts: list[str] = []
    plan = billing.billing_plan or "unknown"
    parts.append(f"- Subscription: {billing.subscription_level.value} (plan={plan})")
    parts.append(f"- Active subscription: {billing.has_active_subscription}")
    if billing.is_deactivated:
        parts.append("- Status: deactivated")
    if billing.trial and billing.trial.is_active:
        parts.append(f"- Trial: active (target={billing.trial.target!r})")
    if billing.startup_program_label:
        parts.append(f"- Startup program: {billing.startup_program_label}")
    if billing.total_current_amount_usd:
        parts.append(f"- Current spend: ${billing.total_current_amount_usd}")
    if billing.projected_total_amount_usd:
        parts.append(f"- Projected spend: ${billing.projected_total_amount_usd}")
    if not parts:
        return None
    return _wrap("Billing context:\n" + "\n".join(parts))


def _build_core_memory_block(core_memory: CoreMemory | None) -> str | None:
    if not core_memory:
        return None
    text = (core_memory.formatted_text or "").strip()
    if not text:
        return None
    return _wrap(f"Core memory (long-lived notes about this project / business):\n{text}")


def _build_mode_block(agent_mode: AgentMode | str | None) -> str | None:
    if not agent_mode:
        return None
    value = agent_mode.value if isinstance(agent_mode, AgentMode) else str(agent_mode)
    return _wrap(f"The user has selected agent mode: {value}. Prefer tools and skills aligned with this mode.")


def _maybe_parse_billing_context(billing: MaxBillingContext | dict | None) -> MaxBillingContext | None:
    if billing is None:
        return None
    if isinstance(billing, MaxBillingContext):
        return billing
    try:
        return MaxBillingContext.model_validate(billing)
    except Exception:
        logger.warning("sandbox_billing_context_parse_failed", exc_info=True)
        return None


def _maybe_parse_ui_context(ui_context: MaxUIContext | dict | None) -> MaxUIContext | None:
    if ui_context is None:
        return None
    if isinstance(ui_context, MaxUIContext):
        return ui_context
    try:
        return MaxUIContext.model_validate(ui_context)
    except Exception:
        logger.warning("sandbox_ui_context_parse_failed", exc_info=True)
        return None


async def build_sandbox_system_reminder(
    *,
    team: Team,
    user: User,
    ui_context: MaxUIContext | dict | None = None,
    billing_context: MaxBillingContext | dict | None = None,
    contextual_tools: dict[str, Any] | None = None,
    agent_mode: AgentMode | str | None = None,
    core_memory: CoreMemory | None = None,
    include_identity: bool = True,
) -> str | None:
    """Compose the ``<system_reminder>`` blocks for the next sandbox turn.

    Returns concatenated reminder content or ``None`` when no reminder applies.
    Each section is its own ``<system_reminder>`` so the harness can summarize
    or drop them independently when the context window fills.
    """
    blocks: list[str] = []

    if include_identity:
        try:
            blocks.append(_build_identity_block(user, team))
        except Exception:
            logger.warning("sandbox_identity_block_failed", exc_info=True)

    parsed_ui = _maybe_parse_ui_context(ui_context)
    parsed_billing = _maybe_parse_billing_context(billing_context)

    config: RunnableConfig = {
        "configurable": {
            "contextual_tools": contextual_tools or {},
            "billing_context": parsed_billing.model_dump() if parsed_billing else None,
        }
    }
    manager = AssistantContextManager(team, user, config=config)

    if parsed_ui is not None:
        try:
            ui_block = await manager._format_ui_context(parsed_ui)
        except Exception:
            logger.warning("sandbox_ui_context_block_failed", exc_info=True)
            ui_block = None
        if ui_block:
            blocks.append(_wrap(ui_block.strip()))

    if contextual_tools:
        try:
            tools_block = await manager._get_contextual_tools_prompt()
        except Exception:
            logger.warning("sandbox_contextual_tools_block_failed", exc_info=True)
            tools_block = None
        if tools_block:
            # _get_contextual_tools_prompt already wraps in <system_reminder>
            blocks.append(tools_block.strip())

    if parsed_billing is not None:
        billing_block = _build_billing_block(parsed_billing)
        if billing_block:
            blocks.append(billing_block)

    mode_block = _build_mode_block(agent_mode)
    if mode_block:
        blocks.append(mode_block)

    memory_block = _build_core_memory_block(core_memory)
    if memory_block:
        blocks.append(memory_block)

    if not blocks:
        return None
    return "\n\n".join(blocks)


def build_sandbox_system_reminder_sync(
    *,
    team: Team,
    user: User,
    ui_context: MaxUIContext | dict | None = None,
    billing_context: MaxBillingContext | dict | None = None,
    contextual_tools: dict[str, Any] | None = None,
    agent_mode: AgentMode | str | None = None,
    core_memory: CoreMemory | None = None,
    include_identity: bool = True,
) -> str | None:
    """Sync wrapper for callers running under WSGI.

    Bridges to the async builder via ``asgiref`` because some context
    providers (e.g. dashboard execution) hit the DB asynchronously.
    """
    from asgiref.sync import async_to_sync

    return async_to_sync(build_sandbox_system_reminder)(
        team=team,
        user=user,
        ui_context=ui_context,
        billing_context=billing_context,
        contextual_tools=contextual_tools,
        agent_mode=agent_mode,
        core_memory=core_memory,
        include_identity=include_identity,
    )


__all__ = [
    "build_sandbox_system_reminder",
    "build_sandbox_system_reminder_sync",
]
