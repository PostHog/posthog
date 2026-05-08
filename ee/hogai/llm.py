import datetime
from collections.abc import Mapping
from functools import cached_property
from typing import Any, cast

from django.conf import settings

import pytz
import anthropic
import structlog
from asgiref.sync import sync_to_async
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.outputs import LLMResult
from langchain_core.prompts import SystemMessagePromptTemplate
from langchain_core.runnables import ensure_config
from langchain_openai import ChatOpenAI
from prometheus_client import Counter
from pydantic import BaseModel, ConfigDict

from posthog.models import Team, User
from posthog.settings import CLOUD_DEPLOYMENT

logger = structlog.get_logger(__name__)

BILLING_SKIPPED_COUNTER = Counter(
    "posthog_ai_billing_skipped_total",
    "Number of AI generations where billing was skipped due to workflow-level override (e.g., impersonation)",
    ["model"],
)

PROJECT_ORG_USER_CONTEXT_PROMPT = """
You are currently in project {{{project_name}}}, which is part of the {{{organization_name}}} organization.
The user's name appears to be {{{user_full_name}}} ({{{user_email}}}). Feel free to use their first name when greeting. DO NOT use this name if it appears possibly fake.
All PostHog app URLs must use relative paths without a domain (no us.posthog.com, eu.posthog.com, app.posthog.com), and omit the `/project/:id/` prefix. Never include `/-/` in URLs.
Use Markdown with descriptive anchor text, for example "[Cohorts view](/cohorts)".

Key URL patterns:
- Settings: `/settings/<section-id>` where section IDs use hyphens, e.g. `/settings/organization-members`, `/settings/environment-replay`, `/settings/user-api-keys`
- Data management: `/data-management/events`, `/data-management/properties`
- Billing: `/organization/billing`
Current time in the project's timezone, {{{project_timezone}}}: {{{project_datetime}}}.
{{#person_on_events_enabled}}
Person-on-events mode is enabled. When querying `person.properties.*` on the events table, values reflect what was set at the time the event was ingested, not the person's current value. The same person can have different property values across different events. Do not suggest workarounds for "query-time" person properties.
{{/person_on_events_enabled}}
{{^person_on_events_enabled}}
Person properties are query-time in this project. `person.properties.*` on the events table always returns the person's current (latest) value, regardless of when the event occurred.
{{/person_on_events_enabled}}
""".strip()

# https://platform.openai.com/docs/guides/flex-processing
OPENAI_FLEX_MODELS = ["o3", "o4-mini", "gpt5", "gpt5-mini", "gpt5-nano"]

# Map "http://", "https://", and "all://" to None in Client's mounts to bypass proxies for MaxChatAnthropic.
_BYPASS_PROXY_MOUNTS: dict[str, None] = {"http://": None, "https://": None, "all://": None}


class MaxChatMixin(BaseModel):
    # We don't want to validate Django models here.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user: User
    team: Team
    max_retries: int | None = None
    stream_usage: bool | None = None
    conversation_start_dt: datetime.datetime | None = None
    """
    The datetime of the start of the conversation. If not provided, the current time will be used.
    """
    billable: bool = False
    """
    Whether the generation will be marked as billable in the usage report for calculating AI billing credits.
    """
    inject_context: bool = True
    """
    Whether to inject project/org/user context into the system prompt.
    Set to False to disable automatic context injection.
    """
    posthog_properties: dict[str, Any] | None = None
    """
    Additional PostHog properties to be added to the $ai_generation event.
    These will be merged with the standard properties like $ai_billable and team_id.
    """

    def model_post_init(self, __context: Any) -> None:
        if self.max_retries is None:
            self.max_retries = 3
        if self.stream_usage is None:
            self.stream_usage = True

    def _get_project_org_user_variables(self) -> dict[str, Any]:
        """Note: this function may perform Postgres queries on `self._team`, `self._team.organization`, and `self._user`."""
        project_timezone = self.team.timezone
        adjusted_dt = self.conversation_start_dt or datetime.datetime.now()
        project_datetime = adjusted_dt.astimezone(tz=pytz.timezone(project_timezone))

        region = CLOUD_DEPLOYMENT or "US"
        if region in ["US", "EU"]:
            region = region.lower()
        else:
            region = "us"

        return {
            "project_name": self.team.name,
            "project_timezone": project_timezone,
            "project_datetime": project_datetime.strftime("%Y-%m-%d %H:%M:%S"),
            "organization_name": self.team.organization.name,
            "user_full_name": self.user.get_full_name(),
            "user_email": self.user.email,
            "deployment_region": region,
            "person_on_events_enabled": self.team.person_on_events_querying_enabled,
        }

    @sync_to_async
    def _aget_project_org_user_variables(self) -> dict[str, Any]:
        return self._get_project_org_user_variables()

    def _get_project_org_system_message(self, project_org_user_variables: dict[str, Any]) -> BaseMessage:
        return SystemMessagePromptTemplate.from_template(
            PROJECT_ORG_USER_CONTEXT_PROMPT, template_format="mustache"
        ).format(**project_org_user_variables)

    def _enrich_messages(self, messages: list[list[BaseMessage]], project_org_user_variables: dict[str, Any]):
        messages = messages.copy()
        for i in range(len(messages)):
            message_sublist = messages[i]
            # In every sublist (which becomes a separate generation) insert our shared prompt at the very end
            # of the system messages block
            for msg_index, msg in enumerate(message_sublist):
                if isinstance(msg, SystemMessage):
                    continue  # Keep going
                else:
                    # Here's our end of the system messages block
                    copied_list = message_sublist.copy()
                    copied_list.insert(msg_index, self._get_project_org_system_message(project_org_user_variables))
                    messages[i] = copied_list
                    break
        return messages

    def _get_effective_billable(self) -> bool:
        """
        Determine the effective billable status for this generation.
        Combines model-level billable setting with workflow-level override from config.
        When is_agent_billable is False (e.g., impersonated sessions), billing is skipped
        regardless of the model's billable setting.
        """
        config = ensure_config()
        is_agent_billable = (config.get("configurable") or {}).get("is_agent_billable", True)

        effective_billable = self.billable and is_agent_billable

        if self.billable and not is_agent_billable:
            # This is really annoying given the interface differences between model providers
            # Once we are behind a proxy, this can be simplified.
            model_name = getattr(self, "model", None) or getattr(self, "model_name", "unknown")
            BILLING_SKIPPED_COUNTER.labels(model=model_name).inc()
            logger.warning("Billing skipped for generation due to workflow-level override")

        return effective_billable

    def _with_posthog_properties(
        self,
        kwargs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a shallow copy of kwargs with PostHog properties, billable flag, and team_id injected into metadata."""
        new_kwargs = dict(kwargs or {})
        metadata = dict(new_kwargs.get("metadata") or {})

        posthog_props = dict(self.posthog_properties or {})
        posthog_props["$ai_billable"] = self._get_effective_billable()
        posthog_props["team_id"] = self.team.id
        posthog_props["ai_product"] = "posthog_ai"

        metadata["posthog_properties"] = posthog_props
        new_kwargs["metadata"] = metadata

        return new_kwargs


class MaxChatOpenAI(MaxChatMixin, ChatOpenAI):
    """PostHog-tuned subclass of ChatOpenAI.

    This subclass automatically injects project, organization, and user context as the final part of the system prompt.
    It also makes sure we retry automatically in case of an OpenAI API error.
    If billable is set to True, the generation will be marked as billable in the usage report for calculating AI billing credits.
    If inject_context is set to False, no context will be included in the system prompt.
    """

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        if settings.IN_EVAL_TESTING and not self.service_tier and self.model_name in OPENAI_FLEX_MODELS:
            self.service_tier = "flex"  # 50% cheaper than default tier, but slower

    def _enrich_responses_api_model_kwargs(self, project_org_user_variables: dict[str, Any]) -> None:
        """Mutate the provided model_kwargs dict in-place, ensuring the project/org/user context is present.

        If the caller has already supplied ``instructions`` we append our context; otherwise we set ``instructions``
        from scratch. This function is intentionally side-effectful and returns ``None``.
        """

        system_msg_content = str(self._get_project_org_system_message(project_org_user_variables).content)

        if self.model_kwargs.get("instructions"):
            # Append to existing instructions
            self.model_kwargs["instructions"] = f"{system_msg_content}\n\n{self.model_kwargs['instructions']}"
        else:
            # Initialise instructions if absent or falsy
            self.model_kwargs["instructions"] = system_msg_content

    def generate(
        self,
        messages: list[list[BaseMessage]],
        *args,
        **kwargs,
    ) -> LLMResult:
        if self.inject_context:
            project_org_user_variables = self._get_project_org_user_variables()
            if self.use_responses_api:
                self._enrich_responses_api_model_kwargs(project_org_user_variables)
            else:
                messages = self._enrich_messages(messages, project_org_user_variables)

        kwargs = self._with_posthog_properties(kwargs)

        return super().generate(messages, *args, **kwargs)

    async def agenerate(
        self,
        messages: list[list[BaseMessage]],
        *args,
        **kwargs,
    ) -> LLMResult:
        if self.inject_context:
            project_org_user_variables = await self._aget_project_org_user_variables()
            if self.use_responses_api:
                self._enrich_responses_api_model_kwargs(project_org_user_variables)
            else:
                messages = self._enrich_messages(messages, project_org_user_variables)

        kwargs = self._with_posthog_properties(kwargs)

        return await super().agenerate(messages, *args, **kwargs)


class MaxChatAnthropic(MaxChatMixin, ChatAnthropic):
    """PostHog-tuned subclass of ChatAnthropic.

    This subclass automatically injects project, organization, and user context as the final part of the system prompt.
    It also makes sure we retry automatically in case of errors.
    """

    bypass_proxy: bool = False
    """
    If True, bypasses egress proxies (HTTP_PROXY/etc)—use for private LLM gateway; if False, default behavior.
    """

    @cached_property
    def _client(self) -> anthropic.Client:
        if not self.bypass_proxy:
            # Defer to upstream so the lru_cache'd httpx client and default proxy behavior are preserved.
            return cast(anthropic.Client, ChatAnthropic._client.func(self))  # type: ignore[attr-defined]
        return anthropic.Client(
            **self._client_params,
            http_client=anthropic.DefaultHttpxClient(**self._bypass_http_client_kwargs()),
        )

    @cached_property
    def _async_client(self) -> anthropic.AsyncClient:
        if not self.bypass_proxy:
            return cast(anthropic.AsyncClient, ChatAnthropic._async_client.func(self))  # type: ignore[attr-defined]
        return anthropic.AsyncClient(
            **self._client_params,
            http_client=anthropic.DefaultAsyncHttpxClient(**self._bypass_http_client_kwargs()),
        )

    def _bypass_http_client_kwargs(self) -> dict[str, Any]:
        """Builds kwargs for ``anthropic.DefaultHttpxClient`` / ``DefaultAsyncHttpxClient`` to bypass the Smokescreen egress proxy without altering other SDK defaults.

        Instead of using ``trust_env=False``, which is ineffective due to SDK internals, we set ``mounts={"http://": None, "https://": None, "all://": None}`` to override environment proxy settings. This approach preserves all other Anthropic SDK connection defaults, such as timeouts, pool limits, and transport settings.

        This depends on the SDK merging the ``mounts`` kwarg on top of its proxy settings and retaining its defaults—guarded by tests in ``test_llm.py``.
        """

        client_params = self._client_params
        kwargs: dict[str, Any] = {
            "base_url": client_params["base_url"],
            "mounts": dict(_BYPASS_PROXY_MOUNTS),
        }
        if "timeout" in client_params:
            # Forward the caller's timeout (langchain-anthropic always sets this key, even when
            # the value is None) so the bypass path matches the non-bypass path's timeout exactly.
            kwargs["timeout"] = client_params["timeout"]
        return kwargs

    def generate(
        self,
        messages: list[list[BaseMessage]],
        *args,
        **kwargs,
    ) -> LLMResult:
        if self.inject_context:
            project_org_user_variables = self._get_project_org_user_variables()
            messages = self._enrich_messages(messages, project_org_user_variables)

        kwargs = self._with_posthog_properties(kwargs)

        return super().generate(messages, *args, **kwargs)

    async def agenerate(
        self,
        messages: list[list[BaseMessage]],
        *args,
        **kwargs,
    ) -> LLMResult:
        if self.inject_context:
            project_org_user_variables = await self._aget_project_org_user_variables()
            messages = self._enrich_messages(messages, project_org_user_variables)

        kwargs = self._with_posthog_properties(kwargs)

        return await super().agenerate(messages, *args, **kwargs)
