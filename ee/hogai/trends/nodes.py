from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from ee.hogai.schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from ee.hogai.schema_generator.utils import SchemaGeneratorOutput
from ee.hogai.taxonomy_agent.nodes import TaxonomyAgentPlannerNode, TaxonomyAgentPlannerToolsNode
from ee.hogai.trends.prompts import (
    react_system_prompt,
    trends_system_prompt,
)
from ee.hogai.trends.toolkit import TRENDS_SCHEMA, TrendsTaxonomyAgentToolkit
from ee.hogai.utils import AssistantState
from posthog.schema import AssistantTrendsQuery


class TrendsPlannerNode(TaxonomyAgentPlannerNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> AssistantState:
        toolkit = TrendsTaxonomyAgentToolkit(self._team)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", react_system_prompt),
            ],
            template_format="mustache",
        )
        return super()._run(state, prompt, toolkit, config=config)


class TrendsPlannerToolsNode(TaxonomyAgentPlannerToolsNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> AssistantState:
        toolkit = TrendsTaxonomyAgentToolkit(self._team)
        return super()._run(state, toolkit, config=config)


TrendsSchemaGeneratorOutput = SchemaGeneratorOutput[AssistantTrendsQuery]


class TrendsGeneratorNode(SchemaGeneratorNode[AssistantTrendsQuery]):
    insight_name = "Trends"
    output_model = TrendsSchemaGeneratorOutput

    def run(self, state: AssistantState, config: RunnableConfig) -> AssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", trends_system_prompt),
            ],
            template_format="mustache",
        )
        return super()._run(state, prompt, config=config)

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4o", temperature=0.2, streaming=True).with_structured_output(
            TRENDS_SCHEMA,
            method="function_calling",
            include_raw=False,
        )


class TrendsGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
