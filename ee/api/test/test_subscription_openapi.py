from typing import Any

from drf_spectacular.generators import SchemaGenerator

from ee.api.subscription import MAX_AI_SUBSCRIPTION_CONTEXTS


def _resolve_schema(schema: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    reference = value.get("$ref")
    if not reference:
        return value
    return schema["components"]["schemas"][reference.rsplit("/", 1)[-1]]


class TestSubscriptionOpenApiContract:
    def test_ai_contexts_are_an_exact_bounded_union(self) -> None:
        schema = SchemaGenerator().get_schema(request=None, public=True)

        for component_name in ("SubscriptionWrite", "PatchedSubscriptionWrite"):
            contexts = schema["components"]["schemas"][component_name]["properties"]["contexts"]

            assert contexts["type"] == "array"
            assert contexts["maxItems"] == MAX_AI_SUBSCRIPTION_CONTEXTS

            item_schemas = [_resolve_schema(schema, item) for item in contexts["items"]["oneOf"]]
            schemas_by_required_id = {item["required"][0]: item for item in item_schemas}

            assert set(schemas_by_required_id) == {"dashboard_id", "insight_id"}
            for field_name, item_schema in schemas_by_required_id.items():
                assert item_schema["type"] == "object"
                assert item_schema["required"] == [field_name]
                assert set(item_schema["properties"]) == {field_name}
                assert item_schema["properties"][field_name]["minimum"] == 1
                assert item_schema["additionalProperties"] is False
