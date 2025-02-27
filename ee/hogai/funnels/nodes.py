from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from ee.hogai.funnels.prompts import FUNNEL_SYSTEM_PROMPT, REACT_SYSTEM_PROMPT
from ee.hogai.funnels.toolkit import FUNNEL_SCHEMA, FunnelsTaxonomyAgentToolkit
from ee.hogai.schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from ee.hogai.schema_generator.utils import SchemaGeneratorOutput
from ee.hogai.taxonomy_agent.nodes import TaxonomyAgentPlannerNode, TaxonomyAgentPlannerToolsNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantFunnelsQuery


class FunnelPlannerNode(TaxonomyAgentPlannerNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit = FunnelsTaxonomyAgentToolkit(self._team)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", REACT_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return super()._run_with_prompt_and_toolkit(state, prompt, toolkit, config=config)


class FunnelPlannerToolsNode(TaxonomyAgentPlannerToolsNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit = FunnelsTaxonomyAgentToolkit(self._team)
        return super()._run_with_toolkit(state, toolkit, config=config)


FunnelsSchemaGeneratorOutput = SchemaGeneratorOutput[AssistantFunnelsQuery]


class FunnelGeneratorNode(SchemaGeneratorNode[AssistantFunnelsQuery]):
    INSIGHT_NAME = "Funnels"
    OUTPUT_MODEL = FunnelsSchemaGeneratorOutput
    OUTPUT_SCHEMA = FUNNEL_SCHEMA

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", FUNNEL_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return super()._run_with_prompt(state, prompt, config=config)


class FunnelGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
