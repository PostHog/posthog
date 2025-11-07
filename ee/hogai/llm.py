import datetime
from collections.abc import Mapping
from typing import Any

from django.conf import settings

import pytz
from asgiref.sync import sync_to_async
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.outputs import LLMResult
from langchain_core.prompts import SystemMessagePromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict

from posthog.models import Team, User
from posthog.settings import CLOUD_DEPLOYMENT

PROJECT_ORG_USER_CONTEXT_PROMPT = """
You are currently in project {{{project_name}}}, which is part of the {{{organization_name}}} organization.
The user's name appears to be {{{user_full_name}}} ({{{user_email}}}). Feel free to use their first name when greeting. DO NOT use this name if it appears possibly fake.
All PostHog app URLs (known by domains us.posthog.com, eu.posthog.com, app.posthog.com) must use absolute paths without a domain, and omitting the `/project/:id/` prefix.
Use Markdown, for example "Find cohorts [in the Cohorts view](/cohorts)".
Current time in the project's timezone, {{{project_timezone}}}: {{{project_datetime}}}.
""".strip()

# https://platform.openai.com/docs/guides/flex-processing
OPENAI_FLEX_MODELS = ["o3", "o4-mini", "gpt5", "gpt5-mini", "gpt5-nano"]


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

    def _with_billing_metadata(
        self,
        kwargs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a shallow copy of kwargs with posthog_ai_billable injected into metadata."""
        new_kwargs = dict(kwargs or {})
        metadata = new_kwargs.get("metadata", {})
        if not isinstance(metadata, dict):
            raise TypeError("Expected 'metadata' to be a dict if provided")
        metadata = dict(metadata)
        metadata["posthog_ai_billable"] = self.billable
        return {**new_kwargs, "metadata": metadata}


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

        kwargs = self._with_billing_metadata(kwargs)

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

        kwargs = self._with_billing_metadata(kwargs)

        return await super().agenerate(messages, *args, **kwargs)


class MaxChatAnthropic(MaxChatMixin, ChatAnthropic):
    """PostHog-tuned subclass of ChatAnthropic.

    This subclass automatically injects project, organization, and user context as the final part of the system prompt.
    It also makes sure we retry automatically in case of errors.
    """

    def generate(
        self,
        messages: list[list[BaseMessage]],
        *args,
        **kwargs,
    ) -> LLMResult:
        if self.inject_context:
            project_org_user_variables = self._get_project_org_user_variables()
            messages = self._enrich_messages(messages, project_org_user_variables)

        kwargs = self._with_billing_metadata(kwargs)

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

        kwargs = self._with_billing_metadata(kwargs)

        return await super().agenerate(messages, *args, **kwargs)
