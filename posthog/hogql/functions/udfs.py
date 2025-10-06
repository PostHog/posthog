from posthog.cloud_utils import is_ci, is_cloud

from .core import HogQLFunctionMeta

UDFS: dict[str, HogQLFunctionMeta] = {
    "aggregate_funnel": HogQLFunctionMeta("aggregate_funnel", 7, 7, aggregate=False),
    "aggregate_funnel_array": HogQLFunctionMeta("aggregate_funnel_array", 7, 7, aggregate=False),
    "aggregate_funnel_cohort": HogQLFunctionMeta("aggregate_funnel_cohort", 7, 7, aggregate=False),
    "aggregate_funnel_test": HogQLFunctionMeta("aggregate_funnel_test", 7, 7, aggregate=False),
    "aggregate_funnel_trends": HogQLFunctionMeta("aggregate_funnel_trends", 8, 8, aggregate=False),
    "aggregate_funnel_array_trends": HogQLFunctionMeta("aggregate_funnel_array_trends", 8, 8, aggregate=False),
    "aggregate_funnel_cohort_trends": HogQLFunctionMeta("aggregate_funnel_cohort_trends", 8, 8, aggregate=False),
    "aggregate_funnel_array_trends_test": HogQLFunctionMeta(
        "aggregate_funnel_array_trends_test", 8, 8, aggregate=False
    ),
}

# We want CI to fail if there is a breaking change and the version hasn't been incremented
if is_cloud() or is_ci():
    from posthog.udf_versioner import augment_function_name

    for v in UDFS.values():
        v.clickhouse_name = augment_function_name(v.clickhouse_name)
