from typing import Any, Literal

from langgraph.errors import NodeInterrupt
from pydantic import BaseModel, Field

from posthog.schema import MultiQuestionFormQuestion

from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolRetryableError

CREATE_FORM_PROMPT = """
Use this tool to collect structured information from the user through a multi-question form.

The form presents questions one at a time with predefined options and optional custom answers.

The tool will pause and wait for the user's answers, then return them as formatted text.

*IMPORTANT*: Do not ask more than 4 questions at a time.
"""


class CreateFormToolArgs(BaseModel):
    questions: list[MultiQuestionFormQuestion] = Field(..., description="The questions to ask the user")


class CreateFormTool(MaxTool):
    name: Literal["create_form"] = "create_form"
    args_schema: type[BaseModel] = CreateFormToolArgs
    description: str = CREATE_FORM_PROMPT

    async def _arun_impl(self, questions: list[MultiQuestionFormQuestion]) -> tuple[str, Any]:
        if not questions:
            raise MaxToolRetryableError("At least one question is required.")
        if len(questions) > 4:
            raise MaxToolRetryableError("Do not ask more than 4 questions at a time.")
        raise NodeInterrupt(None)
