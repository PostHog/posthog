from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig

from posthog.schema import AggregationAxisFormat, AssistantTrendsQuery

from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import PartialAssistantState

from ..schema_generator.nodes import SchemaGeneratorNode, SchemaGeneratorToolsNode
from ..schema_generator.utils import SchemaGeneratorOutput
from .prompts import TRENDS_SYSTEM_PROMPT
from .toolkit import TRENDS_SCHEMA

TrendsSchemaGeneratorOutput = SchemaGeneratorOutput[AssistantTrendsQuery]

# Axis formats that already render the `%` sign themselves, so a literal `%` postfix on top would double it (`50%%`).
_PERCENTAGE_AXIS_FORMATS = {AggregationAxisFormat.PERCENTAGE, AggregationAxisFormat.PERCENTAGE_SCALED}


def _strip_redundant_percentage_postfix(query: AssistantTrendsQuery) -> None:
    """Drop a `%` axis postfix when the axis format already adds one.

    The model tends to pair `aggregationAxisFormat: percentage` with `aggregationAxisPostfix: "%"`,
    which renders every value as e.g. `50%%`. The two are redundant, so we strip the postfix in place.
    """
    trends_filter = query.trendsFilter
    if trends_filter is None or trends_filter.aggregationAxisPostfix is None:
        return
    if (
        trends_filter.aggregationAxisFormat in _PERCENTAGE_AXIS_FORMATS
        and trends_filter.aggregationAxisPostfix.strip() == "%"
    ):
        trends_filter.aggregationAxisPostfix = None


class TrendsGeneratorNode(SchemaGeneratorNode[AssistantTrendsQuery]):
    INSIGHT_NAME = "Trends"
    OUTPUT_MODEL = TrendsSchemaGeneratorOutput
    OUTPUT_SCHEMA = TRENDS_SCHEMA

    def _parse_output(self, output: dict) -> TrendsSchemaGeneratorOutput:
        result = super()._parse_output(output)
        _strip_redundant_percentage_postfix(result.query)
        return result

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", TRENDS_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        )
        return await super()._run_with_prompt(state, prompt, config=config)


class TrendsGeneratorToolsNode(SchemaGeneratorToolsNode):
    pass
