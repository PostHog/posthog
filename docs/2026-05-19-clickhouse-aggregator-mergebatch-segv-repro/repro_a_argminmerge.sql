-- Repro A: SIGSEGV in AggregateFunctionMerge::mergeBatch
-- Maps to row 1 of system.crash_log in
-- ../2026-05-19-clickhouse-aggregator-mergebatch-segv.md
-- Confirmed crashing on ClickHouse 26.3.10.60, aarch64.
--
-- This is the HogQL session_replay_events listing query, slimmed to the
-- columns that matter:
--   - AggregateFunction(argMin, Nullable(String), DateTime64) state in arena
--   - GROUP BY String session_id  -> AggregationMethodString
--   - HAVING uses argMinMerge over the String-state column
--   - 2-shard remote() + distributed_aggregation_memory_efficient = 1
--      -> MergingAggregatedBucketTransform.
--
-- Top crashing frame:
--   IAggregateFunctionHelper<AggregateFunctionMerge>::mergeBatch
--   <- Aggregator::mergeStreamsImpl<AggregationMethodString>
--   <- MergingAggregatedBucketTransform::transform
-- Same fault_address (0x010001000100) as Repro B -> same underlying bug.
--
-- IMPORTANT: run the schema/INSERT and the crashing SELECT in SEPARATE
-- clickhouse-client invocations. Running them in a single --multiquery
-- session occasionally hits an unrelated LOGICAL_ERROR on
-- `max(SimpleAggregateFunction(max, UInt8)) = 0` over remote(), which masks
-- the crash. See README.md for the exact recipe.

-- ============= SETUP (safe to run once) =============

DROP TABLE IF EXISTS repro_a SYNC;

-- Schema mirrors posthog/session_recordings/sql/session_replay_event_sql.py
-- (just the columns the query touches).
CREATE TABLE repro_a
(
    session_id String,
    team_id    Int64,
    first_url           AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    snapshot_library    AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    min_first_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_last_timestamp  SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    active_milliseconds SimpleAggregateFunction(sum, Int64),
    is_deleted          UInt8
)
ENGINE = AggregatingMergeTree
ORDER BY (team_id, session_id)
SETTINGS index_granularity = 512;

-- 500k sessions, ~4 source rows each. snapshot_library = 'posthog-react-native'
-- for 1/3 of rows so HAVING produces survivors.
INSERT INTO repro_a
SELECT
    session_id,
    137648,
    argMinState(first_url,        ts),
    argMinState(snapshot_library, ts),
    min(ts),
    max(ts) + INTERVAL 10 SECOND,
    sum(active_ms),
    0
FROM
(
    SELECT
        concat('sess-', toString(number % 500000))                                       AS session_id,
        toNullable(concat('https://example.com/path/', toString(number % 1000)))         AS first_url,
        toNullable(if(number % 3 = 0, 'posthog-react-native', 'posthog-js'))             AS snapshot_library,
        toDateTime64('2026-05-19 00:00:00', 6, 'UTC') + INTERVAL (number % 86400) SECOND AS ts,
        10000                                                                            AS active_ms
    FROM numbers(2000000)
)
GROUP BY session_id;

-- ============= CRASHING QUERY (run in a fresh client session) =============

SELECT
    s.session_id                                            AS session_id,
    min(toTimeZone(s.min_first_timestamp, 'UTC'))           AS start_time,
    max(toTimeZone(s.max_last_timestamp,  'UTC'))           AS end_time,
    dateDiff('SECOND', start_time, end_time)                AS duration,
    argMinMerge(s.first_url)                                AS first_url,
    sum(s.active_milliseconds) / 1000                       AS active_seconds
FROM remote('clickhouse,clickhouse', currentDatabase(), repro_a) AS s
WHERE s.team_id = 137648
GROUP BY s.session_id
-- toUInt8() cast works around an unrelated LOGICAL_ERROR ("Columns are
-- assumed to be of identical types, but they are different in Nullable")
-- that the optimizer raises for `max(UInt8) = 0` over remote() in 26.3.10.60.
HAVING toUInt8(max(s.is_deleted)) = 0
   AND active_seconds > 5.0
   AND argMinMerge(s.snapshot_library) = 'posthog-react-native'
ORDER BY start_time DESC, s.session_id DESC
LIMIT 51
SETTINGS readonly = 2,
         max_execution_time = 60,
         distributed_aggregation_memory_efficient = 1,
         group_by_two_level_threshold = 1000,
         group_by_two_level_threshold_bytes = 50000,
         max_threads = 8,
         prefer_localhost_replica = 0,
         allow_experimental_analyzer = 0
FORMAT TSV;
