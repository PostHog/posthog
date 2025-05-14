from pydantic import BaseModel, Field

from ee.hogai.utils.helpers import dereference_schema
from posthog.schema import AssistantTrendsQuery

from ..taxonomy_agent.toolkit import TaxonomyAgentToolkit


class final_answer(BaseModel):
    """
    Use this tool to provide the final answer to the user's question.

    Answer in the following format:
    ```
    Series:
    - series 1: event name
        - math operation: total
        - property filter 1:
            - entity
            - property name
            - property type
            - operator
            - property value
        - property filter 2... Repeat for each property filter.
    - series 2: action name
        - action id: `numeric id`
        - math operation: average by `property name`.
        - property filter 1:
            - entity
            - property name
            - property type
            - operator
            - property value
        - property filter 2... Repeat for each property filter.
    - Repeat for each event.

    (if a formula is used)
    Formula:
    `A/B`, where `A` is the first event and `B` is the second event.

    (if a breakdown is used)
    Breakdown by:
    - breakdown 1:
        - entity
        - property name
    - Repeat for each breakdown.

    (if a time period or interval is explicitly mentioned)
    Time period: from and/or to dates or durations. For example: `last 1 week`, `last 12 days`, `from 2025-01-15 to 2025-01-20`, `2025-01-15`, from `last month` to `2024-11-15`.
    Time interval: hour/day/week/month/year
    ```
    """

    final_response: str = Field(
        description="List all events and properties that you want to use to answer the question."
    )


class TrendsTaxonomyAgentToolkit(TaxonomyAgentToolkit):
    def _get_tools(self) -> list[BaseModel]:
        return [*self._default_tools, final_answer]


def generate_trends_schema() -> dict:
    schema = AssistantTrendsQuery.model_json_schema()
    return {
        "name": "output_insight_schema",
        "description": "Outputs the JSON schema of a trends insight",
        "parameters": {
            "type": "object",
            "properties": {
                "query": dereference_schema(schema),
            },
            "additionalProperties": False,
            "required": ["query"],
        },
    }


TRENDS_SCHEMA = generate_trends_schema()
