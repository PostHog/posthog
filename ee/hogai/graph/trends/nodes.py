from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantTrendsQuery

from ..schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from ..schema_generator.utils import SchemaGeneratorOutput
from .prompts import TRENDS_SYSTEM_PROMPT
from .toolkit import TRENDS_SCHEMA

TrendsSchemaGeneratorOutput = SchemaGeneratorOutput[AssistantTrendsQuery]


class TrendsGeneratorNode(SchemaGeneratorNode[AssistantTrendsQuery]):
    INSIGHT_NAME = "Trends"
    OUTPUT_MODEL = TrendsSchemaGeneratorOutput
    OUTPUT_SCHEMA = TRENDS_SCHEMA

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", TRENDS_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return await super()._run_with_prompt(state, prompt, config=config)


class TrendsGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
