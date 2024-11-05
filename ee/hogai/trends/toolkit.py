import json
from functools import cached_property
from typing import Any

from ee.hogai.taxonomy_agent.toolkit import TaxonomyAgentToolkit, ToolkitTool
from posthog.schema import (
    ExperimentalAITrendsQuery,
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


class GenerateTrendTool:
    def _replace_value_in_dict(self, item: Any, original_schema: Any):
        if isinstance(item, list):
            return [self._replace_value_in_dict(i, original_schema) for i in item]
        elif isinstance(item, dict):
            if list(item.keys()) == ["$ref"]:
                definitions = item["$ref"][2:].split("/")
                res = original_schema.copy()
                for definition in definitions:
                    res = res[definition]
                return res
            else:
                return {key: self._replace_value_in_dict(i, original_schema) for key, i in item.items()}
        else:
            return item

    def _flatten_schema(self):
        schema = ExperimentalAITrendsQuery.model_json_schema()

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

        for _ in range(100):
            if "$ref" not in json.dumps(schema):
                break
            schema = self._replace_value_in_dict(schema.copy(), schema.copy())
        del schema["$defs"]
        return schema

    @cached_property
    def schema(self):
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
                    "answer": self._flatten_schema(),
                },
                "additionalProperties": False,
                "required": ["reasoning_steps", "answer"],
            },
        }
