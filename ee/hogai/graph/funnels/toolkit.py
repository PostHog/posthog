from ee.hogai.utils.helpers import dereference_schema
from posthog.schema import AssistantFunnelsQuery


def generate_funnel_schema() -> dict:
    schema = AssistantFunnelsQuery.model_json_schema()
    return {
        "name": "output_insight_schema",
        "description": "Outputs the JSON schema of a product analytics insight",
        "parameters": {
            "type": "object",
            "properties": {
                "query": dereference_schema(schema),
            },
            "additionalProperties": False,
            "required": ["query"],
        },
    }


FUNNEL_SCHEMA = generate_funnel_schema()
