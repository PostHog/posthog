from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from ee.hogai.funnels.prompts import funnel_system_prompt, react_system_prompt
from ee.hogai.funnels.toolkit import FunnelsTaxonomyAgentToolkit
from ee.hogai.schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from ee.hogai.schema_generator.utils import GenerateFunnelTool, SchemaGeneratorOutput
from ee.hogai.taxonomy_agent.nodes import TaxonomyAgentPlannerNode, TaxonomyAgentPlannerToolsNode
from ee.hogai.utils import AssistantState
from posthog.schema import AssistantTrendsQuery


class FunnelPlannerNode(TaxonomyAgentPlannerNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> AssistantState:
        toolkit = FunnelsTaxonomyAgentToolkit(self._team)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", react_system_prompt),
            ],
            template_format="mustache",
        )
        return super()._run(state, prompt, toolkit, config=config)


class FunnelPlannerToolsNode(TaxonomyAgentPlannerToolsNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> AssistantState:
        toolkit = FunnelsTaxonomyAgentToolkit(self._team)
        return super()._run(state, toolkit, config=config)


class FunnelGeneratorNode(SchemaGeneratorNode[AssistantTrendsQuery]):
    insight_name = "Funnels"
    output_model = SchemaGeneratorOutput[AssistantTrendsQuery]

    def run(self, state: AssistantState, config: RunnableConfig) -> AssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", funnel_system_prompt),
            ],
            template_format="mustache",
        )
        return super()._run(state, prompt, config=config)

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4o", temperature=0.2, streaming=True).with_structured_output(
            GenerateFunnelTool().schema,
            method="function_calling",
            include_raw=False,
        )


class TrendsGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
