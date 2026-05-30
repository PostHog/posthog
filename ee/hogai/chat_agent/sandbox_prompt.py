"""Compose the ``systemPrompt`` for a PostHog AI sandbox Run.

``build_posthog_ai_system_prompt`` is a pure async function called once at Run-create time. It
migrates the KEEP/EDIT/DROP segments per ``docs/internal/posthog-ai-migration/04_PROMPTS.md``
§§ 3-6 into one composed string. There are no ``<plan_mode>``/``<core_memory>`` blocks — modes
and core memory are dropped for the sandbox runtime. Dynamic per-turn context (attached entities)
is prepended to the user message by ``ee/hogai/sandbox/context_wrapper.py``, not injected here.

Billing is resolved via the same 3-way logic as the LangGraph ``BillingPromptMixin`` but threaded
through an explicit ``billing_context`` argument so it works without a ``RunnableConfig``. The
billing-access check degrades gracefully to the no-access variant if it cannot be resolved.
"""

import asyncio

import structlog

from posthog.schema import MaxBillingContext

from posthog.models import Team, User

from ee.hogai.chat_agent.prompts.base import (
    PROACTIVENESS_PROMPT,
    PRODUCT_ADVOCACY_PROMPT,
    ROLE_PROMPT,
    TONE_AND_STYLE_PROMPT,
    WRITING_STYLE_PROMPT,
)
from ee.hogai.context import AssistantContextManager
from ee.hogai.core.agent_modes.prompt_builder import (
    ROOT_BILLING_CONTEXT_ERROR_PROMPT,
    ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT,
    ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT,
    ROOT_GROUPS_PROMPT,
)
from ee.hogai.utils.prompt import format_prompt_string

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Edited segments (04_PROMPTS § 3). The KEEP segments are imported verbatim from
# chat_agent/prompts/base.py; the EDIT segments below are rewritten for the sandbox posture
# (no LangGraph idioms, the agent can run code locally, web_search is an ordinary tool).
# ---------------------------------------------------------------------------

# BASIC_FUNCTIONALITY_PROMPT edited: drops the "do not generate code / users can't run code" line
# (in the sandbox the agent can run code locally), keeps the {{{groups_prompt}}} slot.
BASIC_FUNCTIONALITY_PROMPT_REWRITTEN = """
<basic_functionality>
You operate in the user's project and have access to two groups of data: customer data collected via the SDK, and data created directly in PostHog by the user.

Collected data is used for analytics and has the following types:
- Events – recorded events from SDKs that can be aggregated in visual charts and text.
- Persons and groups – recorded individuals or groups of individuals that the user captures using the SDK. Events are always associated with persons and sometimes with groups.{{{groups_prompt}}}
- Sessions – recorded person or group session captured by the user's SDK.
- Properties and property values – provided key-value metadata for segmentation of the collected data (events, actions, persons, groups, etc).
- Session recordings – captured recordings of customer interactions in web or mobile apps.

Created data is used by the user on the PostHog's website to perform business activity and has the following types:
- Actions – unify multiple events or filtering conditions into one.
- Insights – visual and textual representation of the collected data aggregated by different types.
- Data warehouse – connected data sources and custom views for deeper business insights.
- SQL queries – ClickHouse SQL queries that work with collected data and with the data warehouse SQL schema.
- SQL variables – reusable variables for SQL, dashboard, and insight filtering. Search and read them with SQL against `system.insight_variables`; do not look for list/get tools.
- Surveys – various questionnaires that the user conducts to retrieve business insights like an NPS score.
- Dashboards – visual and textual representations of the collected data aggregated by different types.
- Cohorts – groups of persons or groups of persons that the user creates to segment the collected data.
- Feature flags – feature flags that the user creates to control the feature rollout in their product.
- Notebooks – notebooks that the user creates to perform business analysis.
- Error tracking issues – issues that the user creates to track errors in their product.
- User interview topics – topics that drive AI voice agent interviews with selected users, with questions you author.
- Activity logs – a record of changes made to project entities (who changed what, when, and how).

You also have access to tools interacting with the PostHog UI on behalf of the user.

Before using a tool, say what you're about to do, in one sentence.
You may compute small things inline; do not produce code for the user unless asked.

When users ask about SQL variables or query variables, use SQL and query `system.insight_variables` directly. For example:
`SELECT id, name, code_name, type, default_value, values FROM system.insight_variables WHERE name ILIKE '%term%' OR code_name ILIKE '%term%' LIMIT 20`.

When users ask how to log out, sign out, or where the logout button is: it lives in the account menu at the top of the left navigation sidebar – click the organization logo / project name at the top-left, then "Log out" near the bottom of the menu that opens. It is also reachable from the command palette (Cmd/Ctrl+K → type "logout") and from Settings search ("logout"). Logout is NOT a setting under Project, Organization, or User settings pages – do not direct users there.
</basic_functionality>
""".strip()

# SLASH_COMMANDS_PROMPT edited: drops /usage (cloud-agent usage is computed from usage_update
# notifications, not a slash command — 04_PROMPTS § 3 / 02_CORE § 8).
SLASH_COMMANDS_PROMPT_REWRITTEN = """
<slash_commands>
PostHog AI supports slash commands. They are real app features handled by PostHog when users send a message starting with one of these commands:
- `/init` - Set up knowledge about the user's product and business.
- `/feedback [feedback]` - Send feedback about the PostHog AI experience.
- `/ticket` - Create a support ticket from the current conversation when enough context is available.

If a user asks about one of these commands, explain what the command does. If they report a command result looks wrong, treat the command as real and help debug the result.
</slash_commands>
""".strip()

# DOING_TASKS_PROMPT edited: drops the <system_reminder> paragraph (a LangChain idiom we don't
# need in MCP-tool-result land); keeps the search-and-read guidance.
DOING_TASKS_PROMPT_REWRITTEN = """
<doing_tasks>
The user is a product engineer and will primarily request you perform product management tasks. This includes analyzing data, researching reasons for changes, triaging issues, prioritizing features, and more. For these tasks the following steps are recommended:
- Use the `todo_write` tool to plan the task if required
- Use the available search and read tools to understand the project, taxonomy, and the user's query. You are encouraged to use the search and read tools extensively both in parallel and sequentially.
- Answer the user's question using all tools available to you
</doing_tasks>
""".strip()

# TOOL_USAGE_POLICY_PROMPT edited: drops the web_search standalone clause (in the sandbox model
# web_search is an ordinary tool); keeps the docs-pre-check line.
TOOL_USAGE_POLICY_PROMPT_REWRITTEN = """
<tool_usage_policy>
- You can invoke multiple tools within a single response. When a request involves several independent pieces of information, batch your tool calls together for optimal performance
- Retry failed tool calls only if the error proposes retrying, or suggests how to fix tool arguments
- Before describing PostHog support capabilities, data management operations (such as deleting or modifying events), or directing users to contact support, you must search the documentation first using the `search` tool with kind="docs" to verify what is currently offered.
</tool_usage_policy>
""".strip()


async def build_posthog_ai_system_prompt(
    team: Team,
    user: User,
    *,
    context_summary: dict | None = None,
    feature_flag_snapshot: dict | None = None,
) -> str:
    """Compose the ``systemPrompt`` for a PostHog AI sandbox Run.

    Called once at Run creation. The returned string goes into
    ``clientConnection.newSession({ _meta: { systemPrompt } })``. Pure over its inputs; no side
    effects.

    Args:
        team: Resolves the groups prompt and project context block.
        user: Resolves the billing-access check.
        context_summary: Optional small Run-immutable slice (e.g. ``{"billing_context": ...}``).
            Per-turn context (attached entities) does NOT go here — it goes through the user-message
            wrapper.
        feature_flag_snapshot: Frozen view of prompt-affecting flags. Currently unused (the
            sandbox prompt is flag-agnostic), accepted so the caller can thread one evaluation.
    """
    summary = context_summary or {}
    billing_context = _coerce_billing_context(summary.get("billing_context"))

    context_manager = AssistantContextManager(team=team, user=user)

    billing_prompt, group_names = await asyncio.gather(
        _resolve_billing_context(context_manager, billing_context),
        context_manager.get_group_names(),
    )

    groups_prompt = format_prompt_string(ROOT_GROUPS_PROMPT, groups=", ".join(group_names)) if group_names else ""
    basic_functionality = format_prompt_string(
        BASIC_FUNCTIONALITY_PROMPT_REWRITTEN,
        groups_prompt=f" {groups_prompt}" if groups_prompt else "",
    )

    parts: list[str] = [
        f"<identity>\n{ROLE_PROMPT}\n</identity>",
        TONE_AND_STYLE_PROMPT,
        WRITING_STYLE_PROMPT,
        PROACTIVENESS_PROMPT,
        f"<capabilities>\n{basic_functionality}\n</capabilities>",
        SLASH_COMMANDS_PROMPT_REWRITTEN,
        DOING_TASKS_PROMPT_REWRITTEN,
        PRODUCT_ADVOCACY_PROMPT,
        TOOL_USAGE_POLICY_PROMPT_REWRITTEN,
        # ROOT_BILLING_CONTEXT_* constants are already wrapped in <billing_context> tags.
        billing_prompt,
        _build_project_context_block(team),
    ]

    return "\n\n".join(p.strip() for p in parts if p.strip())


def _coerce_billing_context(raw: object) -> MaxBillingContext | None:
    """Normalize a caller-supplied billing context (model, dict, or None) to a model or None."""
    if raw is None:
        return None
    if isinstance(raw, MaxBillingContext):
        return raw
    if isinstance(raw, dict):
        try:
            return MaxBillingContext.model_validate(raw)
        except Exception:
            return None
    return None


async def _resolve_billing_context(
    context_manager: AssistantContextManager,
    billing_context: MaxBillingContext | None,
) -> str:
    """Pick one of the three billing variants — mirrors ``BillingPromptMixin._get_billing_prompt``.

    Degrades gracefully when the access check cannot be resolved (no membership row, DB error):
    falls back to the no-access variant rather than crashing the Run-create path.
    """
    has_billing_context = billing_context is not None
    try:
        has_access = await context_manager.check_user_has_billing_access()
    except Exception as e:
        logger.warning("sandbox_prompt_billing_access_check_failed", error=str(e))
        return ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT

    if has_access and not has_billing_context:
        return ROOT_BILLING_CONTEXT_ERROR_PROMPT

    return (
        ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT
        if has_access and has_billing_context
        else ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT
    )


def _build_project_context_block(team: Team) -> str:
    return f"<project_context>\nProject name: {team.name}.\nDefault timezone: {team.timezone}.\n</project_context>"
