import json
from functools import cached_property
from typing import Any

from openai.types.chat import ChatCompletionToolParam

from posthog.assistant.properties_prompt import PropertiesPrompt
from posthog.models.property_definition import PropertyDefinition
from posthog.schema import ExperimentalAITrendsQuery


class TrendsFunction:
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

    @cached_property
    def _flat_schema(self):
        schema = ExperimentalAITrendsQuery.model_json_schema()

        # Patch `numeric` types
        schema["$defs"]["MathGroupTypeIndex"]["type"] = "number"

        # Clean up the property filters
        for key, title in (
            ("EventPropertyFilter", PropertyDefinition.Type.EVENT.label),
            ("PersonPropertyFilter", PropertyDefinition.Type.PERSON.label),
            ("SessionPropertyFilter", PropertyDefinition.Type.SESSION.label),
            ("FeaturePropertyFilter", "feature"),
            ("CohortPropertyFilter", "cohort"),
        ):
            property_schema = schema["$defs"][key]
            property_schema["properties"]["key"]["description"] = (
                f"Use one of the properties the user has provided in the <{PropertiesPrompt.get_tag_name(title)}> tag."
            )

        for _ in range(100):
            if "$ref" not in json.dumps(schema):
                break
            schema = self._replace_value_in_dict(schema.copy(), schema.copy())
        del schema["$defs"]
        return schema

    def generate_function(self) -> ChatCompletionToolParam:
        return {
            "type": "function",
            "function": {
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
                        "answer": self._flat_schema,
                    },
                },
            },
        }
