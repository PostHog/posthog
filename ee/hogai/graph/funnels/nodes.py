from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from ee.hogai.utils.graph_states import InsightsGraphState, PartialInsightsGraphState
from posthog.schema import AssistantFunnelsQuery

from ..schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from ..schema_generator.utils import SchemaGeneratorOutput
from .prompts import FUNNEL_SYSTEM_PROMPT
from .toolkit import FUNNEL_SCHEMA

FunnelsSchemaGeneratorOutput = SchemaGeneratorOutput[AssistantFunnelsQuery]


class FunnelGeneratorNode(SchemaGeneratorNode[AssistantFunnelsQuery]):
    INSIGHT_NAME = "Funnels"
    OUTPUT_MODEL = FunnelsSchemaGeneratorOutput
    OUTPUT_SCHEMA = FUNNEL_SCHEMA

    async def arun(self, state: InsightsGraphState, config: RunnableConfig) -> PartialInsightsGraphState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", FUNNEL_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return await super()._run_with_prompt(state, prompt, config=config)


class FunnelGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
