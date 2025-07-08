from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from ..schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from ..schema_generator.utils import SchemaGeneratorOutput
from ..taxonomy_agent.nodes import TaxonomyAgentPlannerNode, TaxonomyAgentPlannerToolsNode
from .prompts import REACT_SYSTEM_PROMPT, TRENDS_SYSTEM_PROMPT
from .toolkit import TRENDS_SCHEMA, TrendsTaxonomyAgentToolkit
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantTrendsQuery
from posthog.warehouse.util import database_sync_to_async


class TrendsPlannerNode(TaxonomyAgentPlannerNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit = TrendsTaxonomyAgentToolkit(self._team)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", REACT_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return super()._run_with_prompt_and_toolkit(state, prompt, toolkit, config)

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        # Create toolkit and force evaluation of lazy properties in sync context
        def create_and_initialize_toolkit():
            toolkit = TrendsTaxonomyAgentToolkit(self._team)
            # Force evaluation of cached properties that contain database queries
            _ = toolkit.tools  # This triggers _default_tools which triggers _entity_names which triggers _groups
            return toolkit

        toolkit = await database_sync_to_async(create_and_initialize_toolkit)()
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", REACT_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return await super()._arun_with_prompt_and_toolkit(state, prompt, toolkit, config)


class TrendsPlannerToolsNode(TaxonomyAgentPlannerToolsNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit = TrendsTaxonomyAgentToolkit(self._team)
        return super()._run_with_toolkit(state, toolkit, config)


TrendsSchemaGeneratorOutput = SchemaGeneratorOutput[AssistantTrendsQuery]


class TrendsGeneratorNode(SchemaGeneratorNode[AssistantTrendsQuery]):
    INSIGHT_NAME = "Trends"
    OUTPUT_MODEL = TrendsSchemaGeneratorOutput
    OUTPUT_SCHEMA = TRENDS_SCHEMA

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", TRENDS_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return super()._run_with_prompt(state, prompt, config=config)

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", TRENDS_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return await super()._arun_with_prompt(state, prompt, config=config)


class TrendsGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
