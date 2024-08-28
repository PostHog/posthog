from typing import Optional

import openai
from pydantic import BaseModel

from posthog.assistant.events_prompt import EventsPropmpt
from posthog.assistant.groups_prompt import GroupsPrompt
from posthog.assistant.properties_prompt import PropertiesPrompt
from posthog.assistant.system_prompt import SystemPrompt
from posthog.assistant.trends_function import TrendsFunction
from posthog.models.team.team import Team
from posthog.schema import ExperimentalAITrendsQuery


class AssistantResponse(BaseModel):
    reasoning_steps: Optional[list[str]] = None
    answer: ExperimentalAITrendsQuery


class Assistant:
    _team: Team
    _user_data: str

    def __init__(self, team: Team):
        self._team = team
        self._user_data = self._prepare_user_data()

    def _prepare_system_prompt(self):
        return SystemPrompt(self._team).generate_prompt()

    def _prepare_user_data(self):
        return "".join(
            [
                EventsPropmpt(self._team).generate_prompt(),
                PropertiesPrompt(self._team).generate_prompt(),
                GroupsPrompt(self._team).generate_prompt(),
            ]
        )

    def _prepare_user_prompt(self, prompt: str):
        return f"Answer to my question:\n<question>{prompt}</question>\n{self._user_data}"

    def create_completion(self, messages: list[dict]):
        prompts = [
            {"role": "system", "content": self._prepare_system_prompt()},
            {"role": "user", "content": self._prepare_user_prompt(messages[0]["content"])},
            *messages[1:],
        ]

        completions = openai.chat.completions.create(
            model="gpt-4o-2024-08-06",
            messages=prompts,
            tools=[TrendsFunction().generate_function()],
            tool_choice={"type": "function", "function": {"name": "output_insight_schema"}},
        )

        response = AssistantResponse.model_validate_json(
            completions.choices[0].message.tool_calls[0].function.arguments
        )

        return [
            *messages,
            {"role": "assistant", "content": response.model_dump_json()},
        ]
