from ee.hogai.utils.helpers import dereference_schema
from posthog.schema import AssistantTrendsQuery


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
