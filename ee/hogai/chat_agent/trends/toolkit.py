from posthog.schema import AssistantTrendsQuery

from ee.hogai.utils.helpers import dereference_schema, sort_schema_properties


def generate_trends_schema() -> dict:
    schema = sort_schema_properties(
        AssistantTrendsQuery.model_json_schema(),
        [
            "kind",
            "series",
            "dateRange",
            "interval",
            "trendsFilter",
            "properties",
            "breakdownFilter",
        ],
    )
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
