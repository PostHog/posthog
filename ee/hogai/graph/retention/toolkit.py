from posthog.schema import AssistantRetentionQuery

from ee.hogai.utils.helpers import dereference_schema


def generate_retention_schema() -> dict:
    schema = AssistantRetentionQuery.model_json_schema()
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


RETENTION_SCHEMA = generate_retention_schema()
