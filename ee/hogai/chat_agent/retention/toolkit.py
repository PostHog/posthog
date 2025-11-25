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
            },
            "additionalProperties": False,
            "required": ["query"],
        },
    }


RETENTION_SCHEMA = generate_retention_schema()
