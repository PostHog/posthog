from .core import HogQLFunctionMeta

UDFS: dict[str, HogQLFunctionMeta] = {
    # RowBinary path (default since v12).
    "aggregate_funnel": HogQLFunctionMeta("aggregate_funnel", 7, 7, aggregate=False),
    "aggregate_funnel_array": HogQLFunctionMeta("aggregate_funnel_array", 7, 7, aggregate=False),
    "aggregate_funnel_cohort": HogQLFunctionMeta("aggregate_funnel_cohort", 7, 7, aggregate=False),
    "aggregate_funnel_trends": HogQLFunctionMeta("aggregate_funnel_trends", 8, 8, aggregate=False),
    "aggregate_funnel_array_trends": HogQLFunctionMeta("aggregate_funnel_array_trends", 8, 8, aggregate=False),
    "aggregate_funnel_cohort_trends": HogQLFunctionMeta("aggregate_funnel_cohort_trends", 8, 8, aggregate=False),
    # JSONEachRow mirrors, retained for manual benchmark comparison against the RowBinary path.
    "aggregate_funnel_json": HogQLFunctionMeta("aggregate_funnel_json", 7, 7, aggregate=False),
    "aggregate_funnel_array_json": HogQLFunctionMeta("aggregate_funnel_array_json", 7, 7, aggregate=False),
    "aggregate_funnel_cohort_json": HogQLFunctionMeta("aggregate_funnel_cohort_json", 7, 7, aggregate=False),
    "aggregate_funnel_trends_json": HogQLFunctionMeta("aggregate_funnel_trends_json", 8, 8, aggregate=False),
    "aggregate_funnel_array_trends_json": HogQLFunctionMeta(
        "aggregate_funnel_array_trends_json", 8, 8, aggregate=False
    ),
    "aggregate_funnel_cohort_trends_json": HogQLFunctionMeta(
        "aggregate_funnel_cohort_trends_json", 8, 8, aggregate=False
    ),
    # Python-script debug UDFs.
    "aggregate_funnel_test": HogQLFunctionMeta("aggregate_funnel_test", 7, 7, aggregate=False),
    "aggregate_funnel_array_trends_test": HogQLFunctionMeta(
        "aggregate_funnel_array_trends_test", 8, 8, aggregate=False
    ),
}

# Names here are unversioned; deployments that run versioned UDFs side by side get the
# suffix applied at print time, from EngineConfig.udf_version.
for _meta in UDFS.values():
    _meta.is_udf = True

# JSONDropKeys is an executable UDF like the funnel UDFs, but it is printer-internal (restricted-property blob
# stripping), not HogQL-exposed, so it lives outside UDFS. Its name is unversioned here too; the printer appends
# the EngineConfig.udf_version suffix at print time.
JSON_DROP_KEYS_CLICKHOUSE_NAME = "JSONDropKeys"
