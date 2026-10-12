from typing import Any

from posthog.api.documentation import _hoist_inline_discriminated_unions


def test_nested_discriminated_union_becomes_a_named_component() -> None:
    inner: dict[str, Any] = {
        "discriminator": {"propertyName": "statistic", "mapping": {"mean": "#/components/schemas/WhMean"}},
        "oneOf": [{"$ref": "#/components/schemas/WhMean"}],
    }
    schemas: dict[str, Any] = {
        "Metric": {
            "discriminator": {
                "propertyName": "metric_type",
                "mapping": {"mean": "#/components/schemas/Mean", "warehouse_native": inner},
            },
            "oneOf": [{"$ref": "#/components/schemas/Mean"}, inner],
        }
    }

    hoisted = _hoist_inline_discriminated_unions(schemas)

    ref = "#/components/schemas/MetricWarehouseNative"
    assert hoisted["MetricWarehouseNative"] == inner
    assert hoisted["Metric"]["discriminator"]["mapping"]["warehouse_native"] == ref
    assert hoisted["Metric"]["oneOf"] == [{"$ref": "#/components/schemas/Mean"}, {"$ref": ref}]
    assert schemas["Metric"]["oneOf"][1] is inner
