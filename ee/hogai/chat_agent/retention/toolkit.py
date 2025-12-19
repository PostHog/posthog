from posthog.schema import AssistantRetentionQuery

from ee.hogai.utils.helpers import dereference_schema, sort_schema_properties


def generate_retention_schema() -> dict:
    schema = sort_schema_properties(
        AssistantRetentionQuery.model_json_schema(),
        [
            "kind",
            "retentionFilter",
            "dateRange",
            "properties",
        ],
        property_order_map={
            "AssistantRetentionFilter": [
                "targetEntity",
                "returningEntity",
            ],
        },
    )
    return {
        "name": "output_insight_schema",
        "description": "Outputs the JSON schema of a product analytics insight",
        "parameters": {
            "type": "object",
            "properties": {
                "query": dereference_schema(schema),
                "name": {
                    "type": "string",
                    "description": "Short, concise name of the insight (2-7 words) that will be displayed as a header in the insight tile.",
                },
                "description": {
                    "type": "string",
                    "description": "Short, concise description of the insight (1 sentence)",
                },
            },
            "additionalProperties": False,
            "required": ["query", "name", "description"],
        },
    }


RETENTION_SCHEMA = generate_retention_schema()
