from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from .prompts import RETENTION_SYSTEM_PROMPT, REACT_SYSTEM_PROMPT
from .toolkit import RETENTION_SCHEMA, RetentionTaxonomyAgentToolkit
from ..schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from ..schema_generator.utils import SchemaGeneratorOutput
from ..taxonomy_agent.nodes import TaxonomyAgentPlannerNode, TaxonomyAgentPlannerToolsNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantRetentionQuery


class RetentionPlannerNode(TaxonomyAgentPlannerNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit = RetentionTaxonomyAgentToolkit(self._team)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", REACT_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return super()._run_with_prompt_and_toolkit(state, prompt, toolkit, config)


class RetentionPlannerToolsNode(TaxonomyAgentPlannerToolsNode):
    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        toolkit = RetentionTaxonomyAgentToolkit(self._team)
        return super()._run_with_toolkit(state, toolkit, config=config)


RetentionSchemaGeneratorOutput = SchemaGeneratorOutput[AssistantRetentionQuery]


class RetentionGeneratorNode(SchemaGeneratorNode[AssistantRetentionQuery]):
    INSIGHT_NAME = "Retention"
    OUTPUT_MODEL = RetentionSchemaGeneratorOutput
    OUTPUT_SCHEMA = RETENTION_SCHEMA

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", RETENTION_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return super()._run_with_prompt(state, prompt, config=config)


class RetentionGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
