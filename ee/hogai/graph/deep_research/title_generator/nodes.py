from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from ee.hogai.graph.base import AssistantNode
from ee.hogai.graph.deep_research.title_generator.prompts import TITLE_GENERATION_PROMPT
from ee.hogai.utils.helpers import find_last_message_of_type
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import HumanMessage
from posthog.models.notebook.notebook import Notebook


class DeepResearchNotebookTitleGeneratorNode(AssistantNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        human_message = find_last_message_of_type(state.messages, HumanMessage)
        if not human_message:
            return None

        if not state.notebook:
            return None

        notebook = await Notebook.objects.aget(short_id=state.notebook)

        runnable = (
            ChatPromptTemplate.from_messages([("system", TITLE_GENERATION_PROMPT), ("user", human_message.content)])
            | self._model
            | StrOutputParser()
        )

        title = await runnable.ainvoke({}, config=config)

        notebook.title = title
        if notebook.content is None:
            notebook.content = {"type": "doc", "content": []}
        notebook.content["content"] = [
            {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": title}]}
        ]
        await notebook.asave()

        return None

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4.1-nano", temperature=0.7, max_completion_tokens=100, max_retries=3)
