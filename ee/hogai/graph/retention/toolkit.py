from pydantic import BaseModel, Field

from ee.hogai.utils.helpers import dereference_schema
from posthog.schema import AssistantRetentionQuery

from ..taxonomy_agent.toolkit import TaxonomyAgentToolkit


class final_answer(BaseModel):
    """
    Use this tool to provide the final answer to the user's question.

    Answer in the following format:
    ```
    Activation:
    (if an event is used)
    - event: chosen event name
    (or if an action is used)
    - action id: `numeric id`
    - action name: action name

    Retention:
    - event: chosen event name (can be the same as activation event, or different)
    (or if an action is used)
    - action id: `numeric id`
    - action name: action name

    (if filters are used)
    Filters:
        - property filter 1:
            - entity
            - property name
            - property type
            - operator
            - property value
        - property filter 2... Repeat for each property filter.

    (if a time period is explicitly mentioned)
    Time period: from and/or to dates or durations. For example: `last 1 week`, `last 12 days`, `from 2025-01-15 to 2025-01-20`, `2025-01-15`, from `last month` to `2024-11-15`.
    ```
    """

    final_response: str = Field(
        description="List all events and properties that you want to use to answer the question."
    )


class RetentionTaxonomyAgentToolkit(TaxonomyAgentToolkit):
    def _get_tools(self) -> list[BaseModel]:
        return [*self._default_tools, final_answer]


def generate_retention_schema() -> dict:
    schema = AssistantRetentionQuery.model_json_schema()
    return {
        "name": "output_insight_schema",
        "description": "Outputs the JSON schema of a product analytics insight",
        "parameters": {
            "type": "object",
            "properties": {
                "query": dereference_schema(schema),
                "title": {
                    "type": "string",
                    "description": "Name of the insight. Use the sentence case starting from a captial letter.",
                },
            },
            "additionalProperties": False,
            "required": ["query"],
        },
    }


RETENTION_SCHEMA = generate_retention_schema()
