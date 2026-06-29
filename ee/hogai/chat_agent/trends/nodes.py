from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantTrendsQuery

from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import PartialAssistantState

from ..schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from ..schema_generator.parsers import PydanticOutputParserException
from ..schema_generator.utils import SchemaGeneratorOutput
from .prompts import TRENDS_SYSTEM_PROMPT
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
        # An empty `series` parses fine (Pydantic only requires the field to be present) but blows up at
        # execution with `RequireAtLeastOneSeries`. Reject it here so the retry loop feeds the error back to
        # the LLM and it can self-correct, instead of looping on the same execution-time failure.
        if output.query is None or not output.query.series:
            raise PydanticOutputParserException(
                llm_output=output.query.model_dump_json() if output.query is not None else "",
                validation_message=(
                    "Trends insights require at least one series. Add at least one event, action, "
                    "or group node to the `series` array."
                ),
            )


class TrendsGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
