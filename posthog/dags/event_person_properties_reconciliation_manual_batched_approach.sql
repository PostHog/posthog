-- ============================================================================
-- Event Person Properties Reconciliation - Manual SQL for Production
-- Team ID: 2
-- Bug Window: 2026-01-06 20:01:00 to 2026-01-07 14:52:00
-- 
-- BATCHED BY PERSON EVENT COUNT to avoid O(n²) explosion
-- ============================================================================

-- ============================================================================
-- STEP 1: Create temporary tables
-- ============================================================================

CREATE TEMPORARY TABLE IF NOT EXISTS tmp_set_checkpoints (
    team_id UInt64,
    person_id UUID,
    checkpoint_ts DateTime64(6, 'UTC'),
    accumulated_props String
) ENGINE = MergeTree()
ORDER BY (team_id, person_id, checkpoint_ts);

CREATE TEMPORARY TABLE IF NOT EXISTS tmp_event_person_props_reconciliation (
    team_id UInt64,
    uuid UUID,
    calculated_person_properties String
) ENGINE = MergeTree()
ORDER BY (team_id, uuid);

-- Table to track which persons to process in each batch
CREATE TEMPORARY TABLE IF NOT EXISTS tmp_person_batches (
    person_id UUID,
    event_count UInt64,
    batch_num UInt8
) ENGINE = MergeTree()
ORDER BY (batch_num, person_id);


-- ============================================================================
-- STEP 2: Identify persons and assign to batches
-- ============================================================================

INSERT INTO tmp_person_batches
WITH
    overrides AS (
        SELECT argMax(person_id, version) AS person_id, distinct_id
        FROM person_distinct_id_overrides
        WHERE team_id = 2
        GROUP BY distinct_id
        HAVING ifNull(equals(argMax(is_deleted, version), 0), 0)
    )
SELECT 
    resolved_person_id as person_id,
    count() as event_count,
    multiIf(
        count() < 100, 1,      -- Batch 1: < 100 events (fast)
        count() < 1000, 2,     -- Batch 2: 100-999 events (medium)
        count() < 10000, 3,    -- Batch 3: 1k-9999 events (slow)
        4                       -- Batch 4: 10k+ events (very slow, run separately)
    ) as batch_num
FROM (
    SELECT 
        if(notEmpty(o.distinct_id), o.person_id, e.person_id) as resolved_person_id
    FROM events e
    LEFT JOIN overrides o ON e.distinct_id = o.distinct_id
    WHERE e.team_id = 2
      AND e.timestamp >= '2026-01-06 20:01:00'
      AND e.timestamp <= '2026-01-07 14:52:00'
      AND JSONHas(e.properties, '$set')
)
GROUP BY resolved_person_id;

-- Check batch distribution
SELECT batch_num, count() as persons, sum(event_count) as events, sum(event_count * event_count) as estimated_join_rows
FROM tmp_person_batches
GROUP BY batch_num
ORDER BY batch_num;


-- ============================================================================
-- STEP 3a: Compute checkpoints for BATCH 1 (persons with < 100 $set events)
-- This should be fast
-- ============================================================================

INSERT INTO tmp_set_checkpoints
WITH
    overrides AS (
        SELECT argMax(person_id, version) AS person_id, distinct_id
        FROM person_distinct_id_overrides
        WHERE team_id = 2
        GROUP BY distinct_id
        HAVING ifNull(equals(argMax(is_deleted, version), 0), 0)
    ),
    
    batch_persons AS (
        SELECT person_id FROM tmp_person_batches WHERE batch_num = 1
    ),
    
    base_props AS (
        SELECT 
            id as person_id,
            CAST(JSONExtractKeysAndValues(argMax(properties, version), 'String'), 'Map(String, String)') as props_map
        FROM person
        WHERE team_id = 2
          AND id IN (SELECT person_id FROM batch_persons)
          AND _timestamp < '2026-01-06 20:01:00'
        GROUP BY id
    ),
    
    set_events AS (
        SELECT 
            if(notEmpty(o.distinct_id), o.person_id, e.person_id) as resolved_person_id,
            e.uuid,
            e.timestamp,
            CAST(JSONExtractKeysAndValues(e.properties, '$set', 'String'), 'Map(String, String)') as set_map
        FROM events e
        LEFT JOIN overrides o ON e.distinct_id = o.distinct_id
        WHERE e.team_id = 2
          AND e.timestamp >= '2026-01-06 20:01:00'
          AND e.timestamp <= '2026-01-07 14:52:00'
          AND JSONHas(e.properties, '$set')
          AND if(notEmpty(o.distinct_id), o.person_id, e.person_id) IN (SELECT person_id FROM batch_persons)
    ),
    
    set_key_values AS (
        SELECT 
            target.uuid,
            target.resolved_person_id,
            target.timestamp,
            source_kv.1 as key,
            argMax(source_kv.2, source.timestamp) as value
        FROM set_events target
        INNER JOIN set_events source 
            ON target.resolved_person_id = source.resolved_person_id
            AND source.timestamp <= target.timestamp
        ARRAY JOIN source.set_map as source_kv
        GROUP BY target.uuid, target.resolved_person_id, target.timestamp, source_kv.1
    ),
    
    accumulated_set AS (
        SELECT 
            uuid,
            resolved_person_id,
            timestamp,
            CAST(groupArray((key, value)), 'Map(String, String)') as set_map
        FROM set_key_values
        GROUP BY uuid, resolved_person_id, timestamp
    ),
    
    set_once_per_person AS (
        SELECT 
            resolved_person_id as person_id,
            CAST(groupArray((key, first_value)), 'Map(String, String)') as set_once_map
        FROM (
            SELECT 
                if(notEmpty(o.distinct_id), o.person_id, e.person_id) as resolved_person_id,
                kv.1 as key, 
                argMin(kv.2, e.timestamp) as first_value
            FROM events e
            LEFT JOIN overrides o ON e.distinct_id = o.distinct_id
            ARRAY JOIN JSONExtractKeysAndValues(e.properties, '$set_once', 'String') as kv
            WHERE e.team_id = 2
              AND e.timestamp >= '2026-01-06 20:01:00'
              AND e.timestamp <= '2026-01-07 14:52:00'
              AND JSONHas(e.properties, '$set_once')
              AND if(notEmpty(o.distinct_id), o.person_id, e.person_id) IN (SELECT person_id FROM batch_persons)
            GROUP BY resolved_person_id, kv.1
        )
        GROUP BY person_id
    )

SELECT 
    2 as team_id,
    a.resolved_person_id as person_id,
    a.timestamp as checkpoint_ts,
    toJSONString(
        mapUpdate(
            mapUpdate(
                COALESCE(b.props_map, map()),
                mapFilter((k, v) -> NOT mapContains(COALESCE(b.props_map, map()), k), COALESCE(so.set_once_map, map()))
            ),
            a.set_map
        )
    ) as accumulated_props
FROM accumulated_set a
LEFT JOIN base_props b ON a.resolved_person_id = b.person_id
LEFT JOIN set_once_per_person so ON a.resolved_person_id = so.person_id

SETTINGS 
    max_execution_time = 3600, 
    max_bytes_before_external_group_by = 10000000000,
    allow_experimental_analyzer = 1;


-- ============================================================================
-- STEP 3b: Compute checkpoints for BATCH 2 (persons with 100-999 $set events)
-- ============================================================================

INSERT INTO tmp_set_checkpoints
WITH
    overrides AS (
        SELECT argMax(person_id, version) AS person_id, distinct_id
        FROM person_distinct_id_overrides
        WHERE team_id = 2
        GROUP BY distinct_id
        HAVING ifNull(equals(argMax(is_deleted, version), 0), 0)
    ),
    
    batch_persons AS (
        SELECT person_id FROM tmp_person_batches WHERE batch_num = 2
    ),
    
    base_props AS (
        SELECT 
            id as person_id,
            CAST(JSONExtractKeysAndValues(argMax(properties, version), 'String'), 'Map(String, String)') as props_map
        FROM person
        WHERE team_id = 2
          AND id IN (SELECT person_id FROM batch_persons)
          AND _timestamp < '2026-01-06 20:01:00'
        GROUP BY id
    ),
    
    set_events AS (
        SELECT 
            if(notEmpty(o.distinct_id), o.person_id, e.person_id) as resolved_person_id,
            e.uuid,
            e.timestamp,
            CAST(JSONExtractKeysAndValues(e.properties, '$set', 'String'), 'Map(String, String)') as set_map
        FROM events e
        LEFT JOIN overrides o ON e.distinct_id = o.distinct_id
        WHERE e.team_id = 2
          AND e.timestamp >= '2026-01-06 20:01:00'
          AND e.timestamp <= '2026-01-07 14:52:00'
          AND JSONHas(e.properties, '$set')
          AND if(notEmpty(o.distinct_id), o.person_id, e.person_id) IN (SELECT person_id FROM batch_persons)
    ),
    
    set_key_values AS (
        SELECT 
            target.uuid,
            target.resolved_person_id,
            target.timestamp,
            source_kv.1 as key,
            argMax(source_kv.2, source.timestamp) as value
        FROM set_events target
        INNER JOIN set_events source 
            ON target.resolved_person_id = source.resolved_person_id
            AND source.timestamp <= target.timestamp
        ARRAY JOIN source.set_map as source_kv
        GROUP BY target.uuid, target.resolved_person_id, target.timestamp, source_kv.1
    ),
    
    accumulated_set AS (
        SELECT 
            uuid,
            resolved_person_id,
            timestamp,
            CAST(groupArray((key, value)), 'Map(String, String)') as set_map
        FROM set_key_values
        GROUP BY uuid, resolved_person_id, timestamp
    ),
    
    set_once_per_person AS (
        SELECT 
            resolved_person_id as person_id,
            CAST(groupArray((key, first_value)), 'Map(String, String)') as set_once_map
        FROM (
            SELECT 
                if(notEmpty(o.distinct_id), o.person_id, e.person_id) as resolved_person_id,
                kv.1 as key, 
                argMin(kv.2, e.timestamp) as first_value
            FROM events e
            LEFT JOIN overrides o ON e.distinct_id = o.distinct_id
            ARRAY JOIN JSONExtractKeysAndValues(e.properties, '$set_once', 'String') as kv
            WHERE e.team_id = 2
              AND e.timestamp >= '2026-01-06 20:01:00'
              AND e.timestamp <= '2026-01-07 14:52:00'
              AND JSONHas(e.properties, '$set_once')
              AND if(notEmpty(o.distinct_id), o.person_id, e.person_id) IN (SELECT person_id FROM batch_persons)
            GROUP BY resolved_person_id, kv.1
        )
        GROUP BY person_id
    )

SELECT 
    2 as team_id,
    a.resolved_person_id as person_id,
    a.timestamp as checkpoint_ts,
    toJSONString(
        mapUpdate(
            mapUpdate(
                COALESCE(b.props_map, map()),
                mapFilter((k, v) -> NOT mapContains(COALESCE(b.props_map, map()), k), COALESCE(so.set_once_map, map()))
            ),
            a.set_map
        )
    ) as accumulated_props
FROM accumulated_set a
LEFT JOIN base_props b ON a.resolved_person_id = b.person_id
LEFT JOIN set_once_per_person so ON a.resolved_person_id = so.person_id

SETTINGS 
    max_execution_time = 7200, 
    max_bytes_before_external_group_by = 10000000000,
    allow_experimental_analyzer = 1;


-- ============================================================================
-- STEP 3c: Compute checkpoints for BATCH 3 (persons with 1k-9999 $set events)
-- This will be slower
-- ============================================================================

INSERT INTO tmp_set_checkpoints
WITH
    overrides AS (
        SELECT argMax(person_id, version) AS person_id, distinct_id
        FROM person_distinct_id_overrides
        WHERE team_id = 2
        GROUP BY distinct_id
        HAVING ifNull(equals(argMax(is_deleted, version), 0), 0)
    ),
    
    batch_persons AS (
        SELECT person_id FROM tmp_person_batches WHERE batch_num = 3
    ),
    
    base_props AS (
        SELECT 
            id as person_id,
            CAST(JSONExtractKeysAndValues(argMax(properties, version), 'String'), 'Map(String, String)') as props_map
        FROM person
        WHERE team_id = 2
          AND id IN (SELECT person_id FROM batch_persons)
          AND _timestamp < '2026-01-06 20:01:00'
        GROUP BY id
    ),
    
    set_events AS (
        SELECT 
            if(notEmpty(o.distinct_id), o.person_id, e.person_id) as resolved_person_id,
            e.uuid,
            e.timestamp,
            CAST(JSONExtractKeysAndValues(e.properties, '$set', 'String'), 'Map(String, String)') as set_map
        FROM events e
        LEFT JOIN overrides o ON e.distinct_id = o.distinct_id
        WHERE e.team_id = 2
          AND e.timestamp >= '2026-01-06 20:01:00'
          AND e.timestamp <= '2026-01-07 14:52:00'
          AND JSONHas(e.properties, '$set')
          AND if(notEmpty(o.distinct_id), o.person_id, e.person_id) IN (SELECT person_id FROM batch_persons)
    ),
    
    set_key_values AS (
        SELECT 
            target.uuid,
            target.resolved_person_id,
            target.timestamp,
            source_kv.1 as key,
            argMax(source_kv.2, source.timestamp) as value
        FROM set_events target
        INNER JOIN set_events source 
            ON target.resolved_person_id = source.resolved_person_id
            AND source.timestamp <= target.timestamp
        ARRAY JOIN source.set_map as source_kv
        GROUP BY target.uuid, target.resolved_person_id, target.timestamp, source_kv.1
    ),
    
    accumulated_set AS (
        SELECT 
            uuid,
            resolved_person_id,
            timestamp,
            CAST(groupArray((key, value)), 'Map(String, String)') as set_map
        FROM set_key_values
        GROUP BY uuid, resolved_person_id, timestamp
    ),
    
    set_once_per_person AS (
        SELECT 
            resolved_person_id as person_id,
            CAST(groupArray((key, first_value)), 'Map(String, String)') as set_once_map
        FROM (
            SELECT 
                if(notEmpty(o.distinct_id), o.person_id, e.person_id) as resolved_person_id,
                kv.1 as key, 
                argMin(kv.2, e.timestamp) as first_value
            FROM events e
            LEFT JOIN overrides o ON e.distinct_id = o.distinct_id
            ARRAY JOIN JSONExtractKeysAndValues(e.properties, '$set_once', 'String') as kv
            WHERE e.team_id = 2
              AND e.timestamp >= '2026-01-06 20:01:00'
              AND e.timestamp <= '2026-01-07 14:52:00'
              AND JSONHas(e.properties, '$set_once')
              AND if(notEmpty(o.distinct_id), o.person_id, e.person_id) IN (SELECT person_id FROM batch_persons)
            GROUP BY resolved_person_id, kv.1
        )
        GROUP BY person_id
    )

SELECT 
    2 as team_id,
    a.resolved_person_id as person_id,
    a.timestamp as checkpoint_ts,
    toJSONString(
        mapUpdate(
            mapUpdate(
                COALESCE(b.props_map, map()),
                mapFilter((k, v) -> NOT mapContains(COALESCE(b.props_map, map()), k), COALESCE(so.set_once_map, map()))
            ),
            a.set_map
        )
    ) as accumulated_props
FROM accumulated_set a
LEFT JOIN base_props b ON a.resolved_person_id = b.person_id
LEFT JOIN set_once_per_person so ON a.resolved_person_id = so.person_id

SETTINGS 
    max_execution_time = 14400, 
    max_bytes_before_external_group_by = 10000000000,
    allow_experimental_analyzer = 1;


-- ============================================================================
-- STEP 3d: Compute checkpoints for BATCH 4 (persons with 10k+ $set events)
-- These 61 persons have ~66B estimated join rows - run overnight or skip
-- ============================================================================

-- TODO: For the 61 power users, consider:
-- 1. Running one person at a time
-- 2. Using a streaming Python approach
-- 3. Accepting they'll be slow and running overnight
-- 
-- To run for a single person:
-- WHERE batch_num = 4 AND person_id = 'specific-uuid-here'


-- ============================================================================
-- STEP 4: ASOF JOIN to assign states to ALL events
-- ============================================================================

INSERT INTO tmp_event_person_props_reconciliation
WITH
    overrides AS (
        SELECT argMax(person_id, version) AS person_id, distinct_id
        FROM person_distinct_id_overrides
        WHERE team_id = 2
        GROUP BY distinct_id
        HAVING ifNull(equals(argMax(is_deleted, version), 0), 0)
    ),
    
    base_props AS (
        SELECT 
            id as person_id,
            CAST(JSONExtractKeysAndValues(argMax(properties, version), 'String'), 'Map(String, String)') as props_map
        FROM person
        WHERE team_id = 2
          AND id IN (
              SELECT DISTINCT person_id 
              FROM events 
              WHERE team_id = 2
                AND timestamp >= '2026-01-06 20:01:00'
                AND timestamp <= '2026-01-07 14:52:00'
          )
          AND _timestamp < '2026-01-06 20:01:00'
        GROUP BY id
    ),
    
    set_once_per_person AS (
        SELECT 
            resolved_person_id as person_id,
            CAST(groupArray((key, first_value)), 'Map(String, String)') as set_once_map
        FROM (
            SELECT 
                if(notEmpty(o.distinct_id), o.person_id, e.person_id) as resolved_person_id,
                kv.1 as key, 
                argMin(kv.2, e.timestamp) as first_value
            FROM events e
            LEFT JOIN overrides o ON e.distinct_id = o.distinct_id
            ARRAY JOIN JSONExtractKeysAndValues(e.properties, '$set_once', 'String') as kv
            WHERE e.team_id = 2
              AND e.timestamp >= '2026-01-06 20:01:00'
              AND e.timestamp <= '2026-01-07 14:52:00'
              AND JSONHas(e.properties, '$set_once')
            GROUP BY resolved_person_id, kv.1
        )
        GROUP BY person_id
    ),
    
    target_events AS (
        SELECT 
            e.uuid,
            if(notEmpty(o.distinct_id), o.person_id, e.person_id) as resolved_person_id,
            e.timestamp
        FROM events e
        LEFT JOIN overrides o ON e.distinct_id = o.distinct_id
        WHERE e.team_id = 2
          AND e.timestamp >= '2026-01-06 20:01:00'
          AND e.timestamp <= '2026-01-07 14:52:00'
    )

SELECT 
    2 as team_id,
    t.uuid,
    if(
        c.accumulated_props IS NOT NULL AND c.accumulated_props != '',
        c.accumulated_props,
        toJSONString(
            mapUpdate(
                COALESCE(b.props_map, map()),
                mapFilter(
                    (k, v) -> NOT mapContains(COALESCE(b.props_map, map()), k),
                    COALESCE(so.set_once_map, map())
                )
            )
        )
    ) as calculated_person_properties
FROM target_events t
ASOF LEFT JOIN tmp_set_checkpoints c 
    ON t.resolved_person_id = c.person_id 
    AND t.timestamp >= c.checkpoint_ts
    AND c.team_id = 2
LEFT JOIN base_props b ON t.resolved_person_id = b.person_id
LEFT JOIN set_once_per_person so ON t.resolved_person_id = so.person_id

SETTINGS 
    max_execution_time = 3600, 
    allow_experimental_analyzer = 1;


-- ============================================================================
-- STEP 5: Verify results (run this before the actual update)
-- ============================================================================

SELECT 
    t.uuid,
    e.person_properties as current,
    t.calculated_person_properties as calculated,
    e.person_properties != t.calculated_person_properties as is_different
FROM tmp_event_person_props_reconciliation t
JOIN events e ON t.uuid = e.uuid AND e.team_id = 2
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
