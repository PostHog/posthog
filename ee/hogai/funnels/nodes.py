from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from ee.hogai.funnels.prompts import FUNNEL_SYSTEM_PROMPT, REACT_SYSTEM_PROMPT
from ee.hogai.funnels.toolkit import FUNNEL_SCHEMA, FunnelsTaxonomyAgentToolkit
from ee.hogai.schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from ee.hogai.schema_generator.utils import SchemaGeneratorOutput
from ee.hogai.taxonomy_agent.nodes import TaxonomyAgentPlannerNode, TaxonomyAgentPlannerToolsNode
from ee.hogai.utils import AssistantState
from posthog.schema import AssistantFunnelsQuery


class FunnelPlannerNode(TaxonomyAgentPlannerNode):
    async def run(self, state: AssistantState, config: RunnableConfig) -> AssistantState:
        toolkit = await FunnelsTaxonomyAgentToolkit(self._team).prepare()
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", REACT_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return await super()._run_with_prompt_and_toolkit(state, prompt, toolkit, config=config)


class FunnelPlannerToolsNode(TaxonomyAgentPlannerToolsNode):
    async def run(self, state: AssistantState, config: RunnableConfig) -> AssistantState:
        toolkit = await FunnelsTaxonomyAgentToolkit(self._team).prepare()
        return await super()._run_with_toolkit(state, toolkit, config=config)


FunnelsSchemaGeneratorOutput = SchemaGeneratorOutput[AssistantFunnelsQuery]


class FunnelGeneratorNode(SchemaGeneratorNode[AssistantFunnelsQuery]):
    INSIGHT_NAME = "Funnels"
    OUTPUT_MODEL = FunnelsSchemaGeneratorOutput
    OUTPUT_SCHEMA = FUNNEL_SCHEMA

    async def run(self, state: AssistantState, config: RunnableConfig) -> AssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", FUNNEL_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return await super()._run_with_prompt(state, prompt, config=config)


class FunnelGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
