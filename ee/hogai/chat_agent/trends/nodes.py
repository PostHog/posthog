from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantTrendsQuery

from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import PartialAssistantState

from ..schema_generator.nodes import OutputQualityException, SchemaGeneratorNode, SchemaGeneratorToolsNode
from ..schema_generator.utils import SchemaGeneratorOutput
from .prompts import TRENDS_SYSTEM_PROMPT
from .quality import find_trends_quality_issues
from .toolkit import TRENDS_SCHEMA

TrendsSchemaGeneratorOutput = SchemaGeneratorOutput[AssistantTrendsQuery]


class TrendsGeneratorNode(SchemaGeneratorNode[AssistantTrendsQuery]):
    INSIGHT_NAME = "Trends"
    OUTPUT_MODEL = TrendsSchemaGeneratorOutput
    OUTPUT_SCHEMA = TRENDS_SCHEMA

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", TRENDS_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return await super()._run_with_prompt(state, prompt, config=config)

    async def _quality_check_output(self, output: SchemaGeneratorOutput[AssistantTrendsQuery]) -> None:
        issues = find_trends_quality_issues(output.query)
        if issues:
            raise OutputQualityException(
                llm_output=output.query.model_dump_json(exclude_none=True),
                validation_message="\n".join(issues),
            )


class TrendsGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
