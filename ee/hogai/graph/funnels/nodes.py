from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from .prompts import FUNNEL_SYSTEM_PROMPT, REACT_SYSTEM_PROMPT
from .toolkit import FUNNEL_SCHEMA, FunnelsTaxonomyAgentToolkit
from ..schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from ..schema_generator.utils import SchemaGeneratorOutput
from ..taxonomy_agent.nodes import TaxonomyAgentPlannerNode, TaxonomyAgentPlannerToolsNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantFunnelsQuery


class FunnelPlannerNode(TaxonomyAgentPlannerNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit = FunnelsTaxonomyAgentToolkit(self._team)
        # Pre-load async tools to avoid sync fallback
        await toolkit._aget_tools()
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", REACT_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return await super()._arun_with_prompt_and_toolkit(state, prompt, toolkit, config)


class FunnelPlannerToolsNode(TaxonomyAgentPlannerToolsNode):
    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit = FunnelsTaxonomyAgentToolkit(self._team)
        # Pre-load async tools to avoid sync fallback
        await toolkit._aget_tools()
        return await super()._arun_with_toolkit(state, toolkit, config=config)


FunnelsSchemaGeneratorOutput = SchemaGeneratorOutput[AssistantFunnelsQuery]


class FunnelGeneratorNode(SchemaGeneratorNode[AssistantFunnelsQuery]):
    INSIGHT_NAME = "Funnels"
    OUTPUT_MODEL = FunnelsSchemaGeneratorOutput
    OUTPUT_SCHEMA = FUNNEL_SCHEMA

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", FUNNEL_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return await super()._arun_with_prompt(state, prompt, config=config)


class FunnelGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
