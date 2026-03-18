from posthog.schema import AssistantFunnelsQuery

from ee.hogai.utils.helpers import dereference_schema, sort_schema_properties


def generate_funnel_schema() -> dict:
    schema = sort_schema_properties(
        AssistantFunnelsQuery.model_json_schema(),
        [
            "kind",
            "series",
            "dateRange",
            "interval",
            "funnelsFilter",
            "properties",
            "breakdownFilter",
        ],
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


FUNNEL_SCHEMA = generate_funnel_schema()
