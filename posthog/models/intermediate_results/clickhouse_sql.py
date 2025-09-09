from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import Distributed

# We don't have a typical sharded/distributed/writable setup here.
# Instead, we have a distributed table for reading, and a sharded table for writing.

# The queries that write to this table should always write to a single shard.

# This is because we want to avoid a problem where distributed writes are only eventually consistent, but we usually
# want to read the data back immediately after writing it.

# Using generation_id as the sharding key means that we write the data from one generation to a single shard, and avoid
# this problem. *Reading* from the distributed table afterward is fine, as the query will be routed to the shard that
# has the data.

# To write to a single shard, use the `map_any_host_in_shards` function.


DISTRIBUTED_INTERMEDIATE_RESULTS_TABLE = "intermediate_results"
SHARDED_INTERMEDIATE_RESULTS_TABLE = f"sharded_{DISTRIBUTED_INTERMEDIATE_RESULTS_TABLE}"

INTERMEDIATE_RESULTS_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
(
    team_id Int64,
    generation_id UInt64,
    query_hash String,
    bucket_timestamp DateTime,
    computed_at DateTime DEFAULT now(),
    breakdown_value String,

    -- aggregation values
    unique_uuid_0 AggregateFunction(uniq, UUID),
    unique_string_0 AggregateFunction(uniq, String),
    unique_uint128_0 AggregateFunction(UInt128, String),
    sum_uint64_0 AggregateFunction(sum, UInt64),
    sum_uint64_1 AggregateFunction(sum, Unt64),
    avg_float64_0 AggregateFunction(avg, Float64),
    avg_float64_1 AggregateFunction(avg, Float64),

) ENGINE = {engine}
"""


def SHARDED_INTERMEDIATE_RESULTS_SQL():
    return INTERMEDIATE_RESULTS_BASE_SQL.format(
        table_name=SHARDED_INTERMEDIATE_RESULTS_TABLE,
        on_cluster_clause="",
        engine="MergeTree() PARTITION BY (team_id, toDate(bucket_timestamp)) ORDER BY (team_id, generation_id, query_hash, bucket_timestamp, breakdown_value) SETTINGS index_granularity=8192",
    )


def DISTRIBUTED_INTERMEDIATE_RESULTS_SQL(on_cluster=True):
    return INTERMEDIATE_RESULTS_BASE_SQL.format(
        table_name=DISTRIBUTED_INTERMEDIATE_RESULTS_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=SHARDED_INTERMEDIATE_RESULTS_TABLE,
            sharding_key="cityHash64(generation_id)",
        ),
    )
