from ee.hogai.taxonomy_agent.toolkit import TaxonomyAgentToolkit, ToolkitTool
from ee.hogai.utils import flatten_schema
from posthog.schema import AssistantFunnelsQuery


class FunnelsTaxonomyAgentToolkit(TaxonomyAgentToolkit):
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
                    Sequence:
                    1. event 1
                        - property filter 1:
                            - entity
                            - property name
                            - property type
                            - operator
                            - property value
                        - property filter 2... Repeat for each property filter.
                    2. event 2
                        - property filter 1:
                            - entity
                            - property name
                            - property type
                            - operator
                            - property value
                        - property filter 2... Repeat for each property filter.
                    3. Repeat for each event...

                    (if exclusion steps are used)
                    Exclusions:
                    - exclusion 1
                        - start index: 1
                        - end index: 2
                    - exclusion 2... Repeat for each exclusion...

                    (if a breakdown is used)
                    Breakdown by:
                    - entity
                    - property name
                    ```

                    Args:
                        final_response: List all events and properties that you want to use to answer the question.
                """,
            },
        ]


def generate_funnel_schema() -> dict:
    schema = AssistantFunnelsQuery.model_json_schema()

    # Patch `numeric` types
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
        "description": "Outputs the JSON schema of a product analytics insight",
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


FUNNEL_SCHEMA = generate_funnel_schema()
