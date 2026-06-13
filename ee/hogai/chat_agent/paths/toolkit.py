from posthog.schema import AssistantPathsQuery

from ee.hogai.utils.helpers import dereference_schema, sort_schema_properties


def generate_paths_schema() -> dict:
    schema = sort_schema_properties(
        AssistantPathsQuery.model_json_schema(),
        [
            "kind",
            "pathsFilter",
            "dateRange",
            "properties",
        ],
        property_order_map={
            "AssistantPathsFilter": [
                "includeEventTypes",
                "startPoint",
                "endPoint",
                "stepLimit",
                "excludeEvents",
                "pathGroupings",
                "localPathCleaningFilters",
                "edgeLimit",
                "minEdgeWeight",
                "maxEdgeWeight",
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


PATHS_SCHEMA = generate_paths_schema()
