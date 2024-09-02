from typing import Literal, Optional

from langchain_core.globals import set_debug, set_verbose
from langchain_core.output_parsers.openai_tools import PydanticToolsParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from posthog.assistant.system_prompt import trends_system_prompt
from posthog.assistant.team_prompt import TeamPrompt
from posthog.assistant.trends_function import TrendsFunction
from posthog.models.team.team import Team
from posthog.schema import ExperimentalAITrendsQuery

set_verbose(True)
set_debug(True)


class output_insight_schema(BaseModel):
    reasoning_steps: Optional[list[str]] = None
    answer: ExperimentalAITrendsQuery


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class Conversation(BaseModel):
    messages: list[ChatMessage]


class GenerateTrendsAgent:
    _team: Team

    def __init__(self, team: Team):
        self._team = team

    def bootstrap(self, messages: list[ChatMessage], user_prompt: str | None = None):
        llm = ChatOpenAI(model="gpt-4o").with_structured_output(TrendsFunction().generate_function())
        user_prompt = (
            user_prompt
            or "Answer to my question:\n<question>{{question}}</question>\n" + TeamPrompt(self._team).generate_prompt()
        )

        prompts = ChatPromptTemplate.from_messages(
            [
                ("system", trends_system_prompt),
                ("user", user_prompt),
                *[(message.role, message.content) for message in messages[1:]],
            ],
            template_format="mustache",
        )

        chain = prompts | llm | PydanticToolsParser(tools=[output_insight_schema])  # type: ignore
        return chain
