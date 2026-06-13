from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantPathsQuery

from ee.hogai.utils.types import AssistantState, PartialAssistantState

from ..schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from ..schema_generator.utils import SchemaGeneratorOutput
from .prompts import PATHS_SYSTEM_PROMPT
from .toolkit import PATHS_SCHEMA

PathsSchemaGeneratorOutput = SchemaGeneratorOutput[AssistantPathsQuery]


class PathsGeneratorNode(SchemaGeneratorNode[AssistantPathsQuery]):
    INSIGHT_NAME = "Paths"
    OUTPUT_MODEL = PathsSchemaGeneratorOutput
    OUTPUT_SCHEMA = PATHS_SCHEMA

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", PATHS_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return await super()._run_with_prompt(state, prompt, config=config)


class PathsGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
