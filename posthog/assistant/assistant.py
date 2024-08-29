from typing import Literal, Optional, TypedDict

from langchain_core.output_parsers.openai_tools import PydanticToolsParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from posthog.assistant.events_prompt import EventsPropmpt
from posthog.assistant.groups_prompt import GroupsPrompt
from posthog.assistant.properties_prompt import PropertiesPrompt
from posthog.assistant.system_prompt import trends_examples, trends_system_prompt
from posthog.assistant.trends_function import TrendsFunction
from posthog.models.property_definition import PropertyType
from posthog.models.team.team import Team
from posthog.schema import ExperimentalAITrendsQuery


class output_insight_schema(BaseModel):
    reasoning_steps: Optional[list[str]] = None
    answer: ExperimentalAITrendsQuery


class PropertyNameAndType(TypedDict):
    name: Literal["event", "person", "session", "cohort", "feature"]
    type: PropertyType


class Assistant:
    _team: Team
    _user_data: str
    _llm: ChatOpenAI

    def __init__(self, team: Team):
        self._team = team
        self._llm = ChatOpenAI(model="gpt-4o")

    def create_completion(self, messages: list[ChatCompletionMessageParam]):
        llm = self._llm.bind_tools([TrendsFunction().generate_function()], tool_choice="output_insight_schema")
        prompts = ChatPromptTemplate.from_messages(
            [
                ("system", trends_system_prompt),
                ("user", "Answer to my question:\n<question>{question}</question>\n{user_data}"),
                *[(message["role"], message["content"]) for message in messages[1:]],
            ]
        )

        chain = prompts | llm | PydanticToolsParser(tools=[output_insight_schema])

        message: list = chain.invoke(
            {
                "examples": trends_examples,
                "user_data": "".join(
                    [
                        GroupsPrompt(self._team).generate_prompt(),
                        EventsPropmpt(self._team).generate_prompt(),
                        PropertiesPrompt(self._team).generate_prompt(),
                        # CohortsPrompt(self._team).generate_prompt(),
                    ]
                ),
                "question": messages[0]["content"],
            }
        )

        return [
            *messages,
            {"role": "assistant", "content": message[0].model_dump_json()},
        ]
