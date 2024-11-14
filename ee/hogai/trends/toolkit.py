from ee.hogai.taxonomy_agent.toolkit import TaxonomyAgentToolkit, ToolkitTool
from ee.hogai.utils import flatten_schema
from posthog.schema import (
    AssistantTrendsQuery,
)


class TrendsTaxonomyAgentToolkit(TaxonomyAgentToolkit):
    def _get_tools(self) -> list[ToolkitTool]:
        return [
            *self._default_tools,
            {
                "name": "final_answer",
                "signature": "(final_response: str)",
                "description": """
                    Use this tool to provide the final answer to the user's question.

                    Answer in the following format:
                    ```
                    Events:
                    - event 1
                        - math operation: total
                        - property filter 1:
                            - entity
                            - property name
                            - property type
                            - operator
                            - property value
                        - property filter 2... Repeat for each property filter.
                    - event 2
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
                    ```

                    Args:
                        final_response: List all events and properties that you want to use to answer the question.
                """,
            },
        ]


def generate_trends_schema() -> dict:
    schema = AssistantTrendsQuery.model_json_schema()

    # Patch `numeric` types
    schema["$defs"]["MathGroupTypeIndex"]["type"] = "number"
    property_filters = (
        "EventPropertyFilter",
        "PersonPropertyFilter",
        "SessionPropertyFilter",
        "FeaturePropertyFilter",
        "GroupPropertyFilter",
    )

    # Clean up the property filters
    for key in property_filters:
        property_schema = schema["$defs"][key]
        property_schema["properties"]["key"]["description"] = (
            f"Use one of the properties the user has provided in the plan."
        )

    return {
        "name": "output_insight_schema",
        "description": "Outputs the JSON schema of a funnel insight",
        "parameters": {
            "type": "object",
            "properties": {
                "reasoning_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The reasoning steps leading to the final conclusion that will be shown to the user. Use 'you' if you want to refer to the user.",
                },
                "answer": flatten_schema(schema),
            },
            "additionalProperties": False,
            "required": ["reasoning_steps", "answer"],
        },
    }


TRENDS_SCHEMA = generate_trends_schema()
