import json
from time import sleep
from typing import Optional
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage as LangchainHumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from django.core.serializers.json import DjangoJSONEncoder

from ee.hogai.schema_generator.nodes import (
    BaseMessage,
    LangchainAssistantMessage,
)
from ee.hogai.summarizer.prompts import SUMMARIZER_RESULTS_PROMPT, SUMMARIZER_INSTRUCTION_PROMPT
from ee.hogai.utils import AssistantNode, AssistantNodeName, AssistantState
from posthog.api.services.query import process_query_dict
from posthog.clickhouse.client.execute_async import get_query_status
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.schema import AssistantMessage, VisualizationMessage


class SummarizerNode(AssistantNode):
    name = AssistantNodeName.SUMMARIZER

    def run(self, state: AssistantState, config: RunnableConfig):
        last_message = state["messages"][-1]
        if not isinstance(last_message, VisualizationMessage):
            raise Exception()  # TODO: Better exception
        if last_message.answer is None:
            raise Exception()  # TODO: Better exception

        results_response = process_query_dict(  # type: ignore
            self._team,  # TODO: Add user
            last_message.answer.model_dump(),
            execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE,
        ).model_dump()
        if results_response.get("query_status") and not results_response["query_status"]["complete"]:
            query_id = results_response["query_status"]["id"]
            for i in range(0, 999):
                sleep(i / 2)  # We start at 0.5s and every iteration we wait 0.5s more
                query_status = get_query_status(team_id=self._team.pk, query_id=query_id)
                if query_status.error:
                    # TODO: Handle calculation error gracefully in the assistant
                    break
                if query_status.complete:
                    results_response = query_status.results
                    break

        summarization_prompt = (
            ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        """
Act as an expert product manager. Your task is to summarize query results in a a concise way.
Offer actionable feedback if possible with your context.

The product being analyzed is described as follows:
{{product_description}}""",
                    ),
                ],
                template_format="mustache",
            )
            + self._construct_messages(state)
            + ChatPromptTemplate.from_messages(
                [
                    ("assistant", SUMMARIZER_RESULTS_PROMPT),
                    ("user", SUMMARIZER_INSTRUCTION_PROMPT),
                ],
                template_format="mustache",
            )
        )

        chain = summarization_prompt | self._model

        message = chain.invoke(
            {
                "product_description": self._team.project.product_description,
                "results": json.dumps(results_response["results"], indent=4, cls=DjangoJSONEncoder),  # type: ignore
            },
            config,
        )

        return {"messages": [AssistantMessage(content=str(message.content), done=True)]}

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4o", temperature=0.5, streaming=True)  # Slightly higher temp than earlier steps

    def _construct_messages(
        self, state: AssistantState, validation_error_message: Optional[str] = None
    ) -> list[BaseMessage]:
        messages = state.get("messages", [])

        conversation: list[BaseMessage] = []

        for message in messages:
            if message.type == "human":
                conversation.append(LangchainHumanMessage(content=message.content))
            elif message.type == "ai":
                conversation.append(LangchainAssistantMessage(content=message.content))
            elif message.type == "ai/failure":
                conversation.append(
                    LangchainAssistantMessage(content="Something went wrong while answering.")  # TODO: Better message
                )

        return conversation
