-- Repro B: SIGSEGV in AggregateFunctionAny<SingleValueDataString>::mergeBatch
-- Maps to rows 2-4 of system.crash_log in
-- ../2026-05-19-clickhouse-aggregator-mergebatch-segv.md
-- Confirmed crashing on ClickHouse 26.3.10.60, aarch64.
--
-- Pattern:
--   1. GROUP BY a String key  -> AggregationMethodString (arena-allocated keys)
--   2. multiple aggregates per group, including:
--      - one whose state holds a String in the arena (anyIf(String))
--      - one over DateTime64 (min)
--      - one over UInt8       (max)
--   3. HAVING references a NAMED computed expression built from aggregates
--      (`expiry = min(t) + INTERVAL 30 DAY`) -> hits the bucket-merge path
--   4. distributed_aggregation_memory_efficient + remote() with 2 shards
--      -> MergingAggregatedBucketTransform.
--
-- Removing ANY of those (e.g. dropping max(d), reordering SELECT, dropping
-- the 2nd shard, or setting distributed_aggregation_memory_efficient=0)
-- makes the crash disappear -> arena-layout-dependent.
--
-- Expected: SIGSEGV with fault_address = 0x010001000100 (not a pointer).
-- Recorded in system.crash_log; clickhouse-server restarts; data preserved.

DROP TABLE IF EXISTS repro_b SYNC;

CREATE TABLE repro_b
(
    k String,
    v String,
    t DateTime64(6, 'UTC'),
    n Nullable(Int64),
    d UInt8
)
ENGINE = MergeTree
ORDER BY tuple();

-- 2M rows, ~500k distinct keys -> safely past group_by_two_level_threshold.
INSERT INTO repro_b
SELECT
    concat('k-', toString(number % 500000)),
    concat('v-padded-padded-padded-padded-padded-padded-', toString(rand() % 50000)),
    toDateTime64('2026-05-19 00:00:00', 6, 'UTC') + INTERVAL (number % 86400) SECOND,
    30,
    0
FROM numbers(2000000);

-- Crashing query.
-- remote('clickhouse,clickhouse', ...) addresses the *same* server twice as
-- two distributed shards: this is what forces the
-- MergingAggregatedBucketTransform path on a single-node setup.
SELECT
    k,
    min(t) + INTERVAL 30 DAY AS expiry
FROM remote('clickhouse,clickhouse', currentDatabase(), repro_b)
GROUP BY k
HAVING expiry >= toDateTime64('2026-05-19 00:00:00', 6, 'UTC')
   AND max(d) = 0
   AND anyIf(v, notEmpty(v))
       IN (['v-padded-padded-padded-padded-padded-padded-1'])
ORDER BY k
LIMIT 10
SETTINGS distributed_aggregation_memory_efficient = 1,
         group_by_two_level_threshold = 1000,
         max_threads = 8,
         prefer_localhost_replica = 0,
         allow_experimental_analyzer = 0;
