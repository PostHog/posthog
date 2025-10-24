from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, AssistantRetentionQuery

from ee.hogai.utils.types import AssistantState, PartialAssistantState
from ee.hogai.utils.types.base import AssistantNodeName
from ee.hogai.utils.types.composed import MaxNodeName

from ..schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from ..schema_generator.utils import SchemaGeneratorOutput
from .prompts import RETENTION_SYSTEM_PROMPT
from .toolkit import RETENTION_SCHEMA

RetentionSchemaGeneratorOutput = SchemaGeneratorOutput[AssistantRetentionQuery]


class RetentionGeneratorNode(SchemaGeneratorNode[AssistantRetentionQuery]):
    INSIGHT_NAME = "Retention"
    OUTPUT_MODEL = RetentionSchemaGeneratorOutput
    OUTPUT_SCHEMA = RETENTION_SCHEMA

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.RETENTION_GENERATOR

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        self.dispatcher.message(AssistantMessage(content="Creating retention query"))
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", RETENTION_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return await super()._run_with_prompt(state, prompt, config=config)


class RetentionGeneratorToolsNode(SchemaGeneratorToolsNode):
    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.RETENTION_GENERATOR_TOOLS
