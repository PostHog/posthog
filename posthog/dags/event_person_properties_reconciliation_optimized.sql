-- ============================================================================
-- Event Person Properties Reconciliation - OPTIMIZED with person_id ordering
-- Team ID: 2
-- Bug Window: 2026-01-06 20:01:00 to 2026-01-07 14:52:00
-- 
-- KEY INSIGHT: The events table is ordered by (team_id, toDate(timestamp), event, ...)
-- NOT by person_id. This means any JOIN or GROUP BY on person_id requires hash 
-- operations that hold entire datasets in memory.
--
-- SOLUTION: Single scan to materialize events into a temp table ordered by 
-- (person_id, timestamp). All subsequent operations become O(n) merge operations
-- with bounded memory.
-- ============================================================================


-- ============================================================================
-- STEP 1: Create temporary tables with optimal ordering
-- ============================================================================

-- All events in the window, re-ordered by person_id for efficient merges
-- Only store $set and $set_once as Maps, not the full properties blob
CREATE TEMPORARY TABLE IF NOT EXISTS tmp_events (
    team_id UInt64,
    uuid UUID,
    person_id UUID,
    timestamp DateTime64(6, 'UTC'),
    set_map Map(String, String),
    set_once_map Map(String, String)
) ENGINE = MergeTree()
PARTITION BY sipHash64(timestamp) % 100
ORDER BY (team_id, person_id, timestamp);

-- Accumulated state at each $set event checkpoint
CREATE TEMPORARY TABLE IF NOT EXISTS tmp_set_checkpoints (
    team_id UInt64,
    person_id UUID,
    checkpoint_ts DateTime64(6, 'UTC'),
    accumulated_props String
) ENGINE = MergeTree()
ORDER BY (team_id, person_id, checkpoint_ts);



-- Final results
CREATE TEMPORARY TABLE IF NOT EXISTS tmp_event_person_props_reconciliation (
    team_id UInt64,
    uuid UUID,
    calculated_person_properties String
) ENGINE = MergeTree()
ORDER BY (team_id, uuid);


-- ============================================================================
-- STEP 2: Single scan of events table → tmp_events (ordered by person_id)
-- This is THE ONLY read from the events table. Everything else uses tmp_events.
-- ============================================================================

INSERT INTO tmp_events
WITH
    overrides AS (
        SELECT argMax(person_id, version) AS person_id, distinct_id
        FROM person_distinct_id_overrides
        WHERE team_id = 2
        GROUP BY distinct_id
        HAVING ifNull(equals(argMax(is_deleted, version), 0), 0)
    )
SELECT 
    2 as team_id,
    e.uuid,
    if(notEmpty(o.distinct_id), o.person_id, e.person_id) as person_id,
    e.timestamp,
    CAST(JSONExtractKeysAndValues(e.properties, '$set', 'String'), 'Map(String, String)') as set_map,
    CAST(JSONExtractKeysAndValues(e.properties, '$set_once', 'String'), 'Map(String, String)') as set_once_map
FROM events e
LEFT JOIN overrides o ON e.distinct_id = o.distinct_id
WHERE e.team_id = 2
  AND e.timestamp >= '2026-01-06 20:01:00'
  AND e.timestamp <= '2026-01-07 14:52:00'

SETTINGS max_execution_time = 3600, allow_experimental_analyzer = 1;


-- ============================================================================
-- STEP 3a: Explode set_map into (person_id, timestamp, key, value) rows
-- 
-- For 86k events × 50 keys = 4.3M rows (vs 3.76 BILLION with window function)
-- ============================================================================

CREATE TEMPORARY TABLE IF NOT EXISTS tmp_set_key_values (
    team_id UInt64,
    person_id UUID,
    timestamp DateTime64(6, 'UTC'),
    key String,
    value String
) ENGINE = MergeTree()
ORDER BY (team_id, person_id, key, timestamp);

INSERT INTO tmp_set_key_values
SELECT 
    2 as team_id,
    person_id,
    timestamp,
    kv.1 as key,
    kv.2 as value
FROM tmp_events
ARRAY JOIN set_map as kv
WHERE team_id = 2 AND length(mapKeys(set_map)) > 0

SETTINGS max_execution_time = 600, allow_experimental_analyzer = 1;


-- ============================================================================
-- STEP 3b: Get unique checkpoints and keys per person
-- ============================================================================

CREATE TEMPORARY TABLE IF NOT EXISTS tmp_checkpoints (
    team_id UInt64,
    person_id UUID,
    checkpoint_ts DateTime64(6, 'UTC')
) ENGINE = MergeTree()
ORDER BY (team_id, person_id, checkpoint_ts);

INSERT INTO tmp_checkpoints
SELECT DISTINCT 2 as team_id, person_id, timestamp as checkpoint_ts
FROM tmp_events
WHERE team_id = 2 AND length(mapKeys(set_map)) > 0
SETTINGS max_execution_time = 300, allow_experimental_analyzer = 1;

CREATE TEMPORARY TABLE IF NOT EXISTS tmp_person_keys (
    team_id UInt64,
    person_id UUID,
    key String
) ENGINE = MergeTree()
ORDER BY (team_id, person_id, key);

INSERT INTO tmp_person_keys
SELECT DISTINCT 2 as team_id, person_id, key
FROM tmp_set_key_values WHERE team_id = 2
SETTINGS max_execution_time = 300, allow_experimental_analyzer = 1;


-- ============================================================================
-- STEP 3c: Cross join (checkpoints × keys), ASOF JOIN to get values
-- 
-- For each (checkpoint, key), find the latest value at or before that checkpoint.
-- ASOF JOIN is O(1) per lookup, not O(N).
-- 
-- Output: ~850M rows total, written to disk in batches.
-- ============================================================================

CREATE TEMPORARY TABLE IF NOT EXISTS tmp_checkpoint_key_values (
    team_id UInt64,
    person_id UUID,
    checkpoint_ts DateTime64(6, 'UTC'),
    key String,
    value String
) ENGINE = MergeTree()
ORDER BY (team_id, person_id, checkpoint_ts, key);

-- BATCH 0 of 16 (change "% 16 = 0" for other batches)
INSERT INTO tmp_checkpoint_key_values
SELECT 
    2 as team_id,
    ck.person_id,
    ck.checkpoint_ts,
    ck.key,
    kv.value
FROM (
    SELECT c.person_id, c.checkpoint_ts, pk.key
    FROM tmp_checkpoints c
    INNER JOIN tmp_person_keys pk ON c.person_id = pk.person_id AND pk.team_id = 2
    WHERE c.team_id = 2 AND cityHash64(c.person_id) % 16 = 0
) ck
ASOF LEFT JOIN tmp_set_key_values kv
    ON ck.person_id = kv.person_id
    AND ck.key = kv.key
    AND ck.checkpoint_ts >= kv.timestamp
    AND kv.team_id = 2
WHERE kv.value IS NOT NULL

SETTINGS max_execution_time = 1800, allow_experimental_analyzer = 1;

-- Repeat for batches 1-15: change "% 16 = 0" to "% 16 = 1", etc.


-- ============================================================================
-- STEP 3d: Aggregate key-values back into maps, merge with base + set_once
-- 
-- Process in 16 batches by person hash.
-- ============================================================================

-- BATCH 0 of 16
INSERT INTO tmp_set_checkpoints
WITH
    base_props AS (
        SELECT 
            id as person_id,
            CAST(JSONExtractKeysAndValues(argMax(properties, version), 'String'), 'Map(String, String)') as props_map
        FROM person
        WHERE team_id = 2
          AND id IN (SELECT DISTINCT person_id FROM tmp_checkpoints WHERE team_id = 2 AND cityHash64(person_id) % 16 = 0)
          AND _timestamp < '2026-01-06 20:01:00'
        GROUP BY id
    ),
    
    set_once_per_person AS (
        SELECT 
            person_id,
            CAST(groupArray((key, first_value)), 'Map(String, String)') as merged_set_once_map
        FROM (
            SELECT person_id, kv.1 as key, argMin(kv.2, timestamp) as first_value
            FROM tmp_events
            ARRAY JOIN set_once_map as kv
            WHERE team_id = 2 AND length(mapKeys(set_once_map)) > 0 AND cityHash64(person_id) % 16 = 0
            GROUP BY person_id, kv.1
        )
        GROUP BY person_id
    ),
    
    checkpoint_maps AS (
        SELECT 
            person_id,
            checkpoint_ts,
            CAST(groupArray((key, value)), 'Map(String, String)') as accumulated_set_map
        FROM tmp_checkpoint_key_values
        WHERE team_id = 2 AND cityHash64(person_id) % 16 = 0
        GROUP BY person_id, checkpoint_ts
    )

SELECT 
    2 as team_id,
    cm.person_id,
    cm.checkpoint_ts,
    toJSONString(
        mapUpdate(
            mapUpdate(
                COALESCE(b.props_map, map()),
                mapFilter(
                    (k, v) -> NOT mapContains(COALESCE(b.props_map, map()), k),
                    COALESCE(so.merged_set_once_map, map())
                )
            ),
            cm.accumulated_set_map
        )
    ) as accumulated_props
FROM checkpoint_maps cm
LEFT JOIN base_props b ON cm.person_id = b.person_id
LEFT JOIN set_once_per_person so ON cm.person_id = so.person_id

SETTINGS 
    max_execution_time = 1800,
    max_bytes_before_external_group_by = 10000000000,
    allow_experimental_analyzer = 1;

-- Repeat for batches 1-15: change "% 16 = 0" to "% 16 = 1", etc.


-- ============================================================================
-- STEP 4: ASOF JOIN to assign accumulated state to ALL events
-- 
-- Both tmp_events and tmp_set_checkpoints are ordered by (person_id, timestamp)
-- so this ASOF JOIN is an efficient merge operation.
-- ============================================================================

INSERT INTO tmp_event_person_props_reconciliation
WITH
    -- Base properties (for events with no prior $set)
    base_props AS (
        SELECT 
            id as person_id,
            CAST(JSONExtractKeysAndValues(argMax(properties, version), 'String'), 'Map(String, String)') as props_map
        FROM person
        WHERE team_id = 2
          AND id IN (SELECT DISTINCT person_id FROM tmp_events WHERE team_id = 2)
          AND _timestamp < '2026-01-06 20:01:00'
        GROUP BY id
    ),
    
    -- $set_once for all persons
    set_once_per_person AS (
        SELECT 
            person_id,
            CAST(groupArray((key, first_value)), 'Map(String, String)') as merged_set_once_map
        FROM (
            SELECT 
                person_id,
                kv.1 as key, 
                argMin(kv.2, timestamp) as first_value
            FROM tmp_events
            ARRAY JOIN set_once_map as kv
            WHERE team_id = 2 AND length(mapKeys(set_once_map)) > 0
            GROUP BY person_id, kv.1
        )
        GROUP BY person_id
    )

SELECT 
    2 as team_id,
    t.uuid,
    if(
        c.accumulated_props IS NOT NULL AND c.accumulated_props != '',
        -- Event has a prior $set checkpoint - use pre-computed accumulated props
        c.accumulated_props,
        -- No prior $set - just base_props + set_once
        toJSONString(
            mapUpdate(
                COALESCE(b.props_map, map()),
                mapFilter(
                    (k, v) -> NOT mapContains(COALESCE(b.props_map, map()), k),
                    COALESCE(so.merged_set_once_map, map())
                )
            )
        )
    ) as calculated_person_properties
FROM tmp_events t
ASOF LEFT JOIN tmp_set_checkpoints c 
    ON t.person_id = c.person_id 
    AND t.timestamp >= c.checkpoint_ts
    AND c.team_id = 2
LEFT JOIN base_props b ON t.person_id = b.person_id
LEFT JOIN set_once_per_person so ON t.person_id = so.person_id
WHERE t.team_id = 2

SETTINGS 
    max_execution_time = 3600, 
    allow_experimental_analyzer = 1;


-- ============================================================================
-- STEP 5: Verify results
-- ============================================================================

SELECT 
    t.uuid,
    e.person_properties as current,
    t.calculated_person_properties as calculated,
    e.person_properties != t.calculated_person_properties as is_different
FROM tmp_event_person_props_reconciliation t
JOIN events e ON t.uuid = e.uuid AND e.team_id = 2
WHERE t.team_id = 2
LIMIT 100;


-- ============================================================================
-- STEP 6: Update events (DANGER: this actually modifies data)
-- ============================================================================

-- ALTER TABLE sharded_events
-- UPDATE person_properties = tmp.calculated_person_properties
-- FROM tmp_event_person_props_reconciliation AS tmp
-- WHERE sharded_events.team_id = 2
--   AND sharded_events.uuid = tmp.uuid
--   AND tmp.team_id = 2
-- SETTINGS mutations_sync = 0;


-- ============================================================================
-- Cleanup (optional)
-- ============================================================================

-- DROP TABLE IF EXISTS tmp_events;
-- DROP TABLE IF EXISTS tmp_set_checkpoints;
-- DROP TABLE IF EXISTS tmp_event_person_props_reconciliation;
