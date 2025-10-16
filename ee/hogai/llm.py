import datetime
from typing import TYPE_CHECKING, Any

from django.conf import settings

import pytz
from asgiref.sync import sync_to_async
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.outputs import LLMResult
from langchain_core.prompts import SystemMessagePromptTemplate
from langchain_openai import ChatOpenAI

from posthog.settings import CLOUD_DEPLOYMENT

if TYPE_CHECKING:
    from posthog.models import Team, User

PROJECT_ORG_USER_CONTEXT_PROMPT = """
You are currently in project {{{project_name}}}, which is part of the {{{organization_name}}} organization.
The user's name appears to be {{{user_full_name}}} ({{{user_email}}}). Feel free to use their first name when greeting. DO NOT use this name if it appears possibly fake.
The user is accessing the PostHog App from the "{{{deployment_region}}}" region, therefore all PostHog App URLs should be prefixed with the region, e.g. https://{{{deployment_region}}}.posthog.com
Current time in the project's timezone, {{{project_timezone}}}: {{{project_datetime}}}.
""".strip()

# https://platform.openai.com/docs/guides/flex-processing
OPENAI_FLEX_MODELS = ["o3", "o4-mini", "gpt5", "gpt5-mini", "gpt5-nano"]


class MaxChatOpenAI(ChatOpenAI):
    """PostHog-tuned subclass of ChatOpenAI.

    This subclass automatically injects project, organization, and user context as the final part of the system prompt.
    It also makes sure we retry automatically in case of an OpenAI API error.
    """

    def __init__(self, *args, user: "User", team: "Team", **kwargs):
        if "max_retries" not in kwargs:
            kwargs["max_retries"] = 3
        if "stream_usage" not in kwargs:
            kwargs["stream_usage"] = True
        if settings.IN_EVAL_TESTING and "service_tier" not in kwargs and kwargs["model"] in OPENAI_FLEX_MODELS:
            kwargs["service_tier"] = "flex"  # 50% cheaper than default tier, but slower
        super().__init__(*args, **kwargs)
        self._user = user
        self._team = team

    def _get_project_org_user_variables(self) -> dict[str, Any]:
        """Note: this function may perform Postgres queries on `self._team`, `self._team.organization`, and `self._user`."""
        project_timezone = self._team.timezone
        project_datetime = datetime.datetime.now(tz=pytz.timezone(project_timezone))

        region = CLOUD_DEPLOYMENT or "US"
        if region in ["US", "EU"]:
            region = region.lower()
        else:
            region = "us"

        return {
            "project_name": self._team.name,
            "project_timezone": project_timezone,
            "project_datetime": project_datetime.strftime("%Y-%m-%d %H:%M:%S"),
            "organization_name": self._team.organization.name,
            "user_full_name": self._user.get_full_name(),
            "user_email": self._user.email,
            "deployment_region": region,
        }

    def _get_project_org_system_message(self, project_org_user_variables: dict[str, Any]) -> BaseMessage:
        return SystemMessagePromptTemplate.from_template(
            PROJECT_ORG_USER_CONTEXT_PROMPT, template_format="mustache"
        ).format(**project_org_user_variables)

    def _enrich_messages(self, messages: list[list[BaseMessage]], project_org_user_variables: dict[str, Any]):
        for message_sublist in messages:
            # In every sublist (which becomes a separate generation) insert our shared prompt at the very end
            # of the system messages block
            for msg_index, msg in enumerate(message_sublist):
                if isinstance(msg, SystemMessage):
                    continue  # Keep going
                else:
                    # Here's our end of the system messages block
                    message_sublist.insert(msg_index, self._get_project_org_system_message(project_org_user_variables))
                    break

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
        project_org_user_variables = self._get_project_org_user_variables()
        if self.use_responses_api:
            self._enrich_responses_api_model_kwargs(project_org_user_variables)
        else:
            self._enrich_messages(messages, project_org_user_variables)
        return super().generate(messages, *args, **kwargs)

    async def agenerate(
        self,
        messages: list[list[BaseMessage]],
        *args,
        **kwargs,
    ) -> LLMResult:
        project_org_user_variables = await sync_to_async(self._get_project_org_user_variables)()
        if self.use_responses_api:
            self._enrich_responses_api_model_kwargs(project_org_user_variables)
        else:
            self._enrich_messages(messages, project_org_user_variables)
        return await super().agenerate(messages, *args, **kwargs)
