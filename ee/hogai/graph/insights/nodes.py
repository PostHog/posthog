from typing import Literal
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

import structlog


from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import (
    AssistantMessage,
)
from ee.hogai.graph.base import AssistantNode


class InsightSearchNode(AssistantNode):
    logger = structlog.get_logger(__name__)

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        conversation = self._get_conversation(config["configurable"]["thread_id"])  # noqa: F841

        self.logger.info(f"The team is: {self._team} | {self._user}")

        # perform a django query to get the insights

        return PartialAssistantState(
            messages=[
                AssistantMessage(
                    content="Checking insights...",
                    id=str(uuid4()),
                )
            ]
        )

    def router(self, state: AssistantState) -> Literal["end"]:
        return "end"

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4.1-nano", temperature=0.7, max_completion_tokens=100)
