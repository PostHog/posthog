import logging
from typing import cast
from langchain_openai import ChatOpenAI
from ee.hogai.graph.deep_research.base import DeepResearchNode
from ee.hogai.graph.deep_research.final_summarizer.prompts import AGENT_FINAL_SUMMARY_PROMPT
from ee.hogai.graph.deep_research.serializer import DeepResearchSerializer
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from langchain_core.runnables import RunnableConfig
from langchain_core.prompts import ChatPromptTemplate
from uuid import uuid4

from langchain_core.messages import (
    AIMessage as LangchainAIMessage,
)

from posthog.models.notebook.notebook import Notebook
from posthog.schema import AssistantMessage

logger = logging.getLogger(__name__)


class DeepResearchFinalSummarizerNode(DeepResearchNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        deep_research_plan = state.deep_research_plan
        if not deep_research_plan:
            raise ValueError("No deep research plan found.")
        results = []
        for todo in deep_research_plan.todos:
            if todo.status != "completed":
                continue
            _result = deep_research_plan.results.get(todo.short_id, None)
            if not _result:
                continue
            results.append(_result)

        existing_report = "\n".join(results)

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", AGENT_FINAL_SUMMARY_PROMPT),
            ],
            template_format="mustache",
        )

        chain = prompt | self._get_model(state, config)

        message = await chain.ainvoke(
            {"existing_report": existing_report},
            config,
        )
        message = cast(LangchainAIMessage, message)

        if not state.notebook:
            raise ValueError("No notebook found.")
        notebook_serializer = DeepResearchSerializer()
        notebook = await Notebook.objects.aget(short_id=state.notebook)
        insights_map = notebook_serializer.extract_visualizations_from_notebook_json(notebook.content)
        await notebook_serializer.save_to_notebook(notebook, str(message.content), insights_map, overwrite=True)

        return PartialAssistantState(
            messages=[
                AssistantMessage(
                    content="Your report is ready!",
                    id=str(uuid4()),
                ),
            ]
        )

    def _get_model(self, state: AssistantState, config: RunnableConfig):
        return ChatOpenAI(model="o4-mini", temperature=0.3, streaming=True, stream_usage=True, max_retries=3)
