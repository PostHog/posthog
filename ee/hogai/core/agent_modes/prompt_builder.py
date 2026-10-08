import asyncio
from abc import ABC, abstractmethod
from typing import Generic

from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from posthoganalytics import capture_exception

from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_catalog.backend.facade.api import compute_drift, metrics_for_team, metrics_visible_to_user
from products.data_catalog.backend.facade.enums import MetricStatus

from ee.hogai.context import AssistantContextManager
from ee.hogai.core.mixins import AssistantContextMixin
from ee.hogai.core.shared_prompts import CORE_MEMORY_PROMPT
from ee.hogai.utils.prompt import format_prompt_string
from ee.hogai.utils.types.base import AssistantState, StateType

ROOT_GROUPS_PROMPT = """
<groups>
The user has defined the following groups: {{{groups}}}.
</groups>
""".strip()

ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT = """
<billing_context>
If the user asks about billing, their subscription, their usage, or their spending, use the `read_data` tool with the `billing_info` kind to answer.
You can use the information retrieved to check which PostHog products and add-ons the user has activated, how much they are spending, their usage history across all products in the last 30 days, as well as trials, spending limits, billing period, and more.
If the user wants to reduce their spending, always call this tool to get suggestions on how to do so.
If an insight shows zero data, it could mean either the query is looking at the wrong data or there was a temporary data collection issue. You can investigate potential dips in usage/captured data using the billing tool.
</billing_context>
""".strip()

ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT = """
<billing_context>
The user does not have admin access to view detailed billing information. They would need to contact an organization admin for billing details.
In case the user asks to debug problems that relate to billing, suggest them to contact an admin.
</billing_context>
""".strip()

ROOT_BILLING_CONTEXT_ERROR_PROMPT = """
<billing_context>
If the user asks about billing, their subscription, their usage, or their spending, suggest them to talk to PostHog support.
</billing_context>
""".strip()


ROOT_GOVERNED_METRICS_PROMPT = """
<governed_metrics>
This project defines approved metrics in its data catalog. An approved metric is the canonical definition of a business measure. It outranks core memory, saved insights, and any query you write yourself.
Approved metrics: {{{metric_names}}}.

- A request for a measure is any count, sum, rate, percentage, average, or conversion of something the product records, or a breakdown or comparison of one. Examples: "how many X", "X per week", "conversion from A to B".
- Before you query data for a measure, use the `read_data` tool with the `data_catalog_metrics` kind to find a matching metric. Do this even when the user does not mention the catalog, and even when core memory or an insight describes the measure differently.
- When an approved metric that is not drifted answers the request, run it with the `read_data` tool with the `data_catalog_metric` kind. Report its result. Do not write a different query for the same number.
- Some metrics return calculation steps instead of a result. If the metric is approved and not drifted, follow only those steps to calculate it. That result is canonical.
- Never present the result of a proposed or drifted metric as the canonical answer. If you calculate a number without an approved metric, say that it is not the catalog's canonical number.
- When different metrics can each answer the request, ask the user one clarifying question.
- If no metric matches, say that you checked the data catalog. Label any number you calculate as not canonical.
</governed_metrics>
""".strip()

# Caps the prompt size for large catalogs. The agent lists the full catalog with `read_data`.
ROOT_GOVERNED_METRICS_MAX_NAMES = 50


class PromptBuilder(ABC, Generic[StateType]):
    @abstractmethod
    async def get_prompts(self, state: StateType, config: RunnableConfig) -> list[BaseMessage]: ...


class AgentPromptBuilder(PromptBuilder[AssistantState]):
    def __init__(self, team: Team, user: User, context_manager: AssistantContextManager):
        self._team = team
        self._user = user
        self._context_manager = context_manager

    @abstractmethod
    async def get_prompts(self, state: AssistantState, config: RunnableConfig) -> list[BaseMessage]: ...


class BillingPromptMixin:
    _context_manager: AssistantContextManager

    async def _get_billing_prompt(self) -> str:
        """Get billing information including whether to include the billing tool and the prompt.
        Returns:
            str: prompt
        """
        has_billing_context = self._context_manager.get_billing_context() is not None
        has_access = await self._context_manager.check_user_has_billing_access()

        if has_access and not has_billing_context:
            return ROOT_BILLING_CONTEXT_ERROR_PROMPT

        prompt = (
            ROOT_BILLING_CONTEXT_WITH_ACCESS_PROMPT
            if has_access and has_billing_context
            else ROOT_BILLING_CONTEXT_WITH_NO_ACCESS_PROMPT
        )
        return prompt


def _visible_approved_metric_names(team: Team, user: User) -> list[str]:
    # Hides metrics over tables the user cannot read, like the `read_data` metric kinds do.
    user_access_control = UserAccessControl(user=user, team=team)
    if not user_access_control.check_access_level_for_resource("data_catalog", "viewer"):
        return []
    # metrics_visible_to_user builds the full warehouse schema, and this prompt is rebuilt on every model turn.
    # Skip that build when the team has no approved metrics.
    if not metrics_for_team(team).filter(status=MetricStatus.APPROVED).exists():
        return []
    approved = list(
        metrics_visible_to_user(team, user, user_access_control).filter(status=MetricStatus.APPROVED).order_by("name")
    )
    drift = compute_drift(approved)
    return [metric.name for metric in approved if not drift[metric.id]]


class GovernedMetricsPromptMixin:
    _team: Team
    _user: User

    async def _get_governed_metrics_prompt(self) -> str:
        try:
            names = await database_sync_to_async(_visible_approved_metric_names)(self._team, self._user)
        except Exception as e:
            # The catalog is optional context; a failed read must not block the conversation.
            capture_exception(e)
            return ""
        if not names:
            return ""
        shown = ", ".join(names[:ROOT_GOVERNED_METRICS_MAX_NAMES])
        if len(names) > ROOT_GOVERNED_METRICS_MAX_NAMES:
            shown += f", and {len(names) - ROOT_GOVERNED_METRICS_MAX_NAMES} more"
        return format_prompt_string(ROOT_GOVERNED_METRICS_PROMPT, metric_names=shown)


class AgentPromptBuilderBase(AgentPromptBuilder, AssistantContextMixin, BillingPromptMixin, GovernedMetricsPromptMixin):
    """Base class for agent prompt builders with shared logic for gathering context."""

    @abstractmethod
    def _get_system_prompt(self) -> str:
        """Return the formatted system prompt. Must be implemented by subclasses."""
        ...

    def _get_core_memory_prompt(self) -> str:
        """Return the core memory prompt template. Override in subclasses if needed."""
        return CORE_MEMORY_PROMPT

    async def get_prompts(self, state: AssistantState, config: RunnableConfig) -> list[BaseMessage]:
        billing_prompt, core_memory, groups, governed_metrics = await asyncio.gather(
            self._get_billing_prompt(),
            self._aget_core_memory_text(),
            self._context_manager.get_group_names(),
            self._get_governed_metrics_prompt(),
        )

        format_args = {
            "groups_prompt": f" {format_prompt_string(ROOT_GROUPS_PROMPT, groups=', '.join(groups))}" if groups else "",
            "core_memory": core_memory,
            "billing_context": billing_prompt,
            "governed_metrics": governed_metrics,
        }

        return ChatPromptTemplate.from_messages(
            [
                ("system", self._get_system_prompt()),
                *([("system", "{{{governed_metrics}}}")] if governed_metrics else []),
                ("system", self._get_core_memory_prompt()),
            ],
            template_format="mustache",
        ).format_messages(**format_args)
