from django.conf import settings

CREATE_PERSONS_BATCH_EXPORT_VIEW = f"""
CREATE OR REPLACE VIEW persons_batch_export ON CLUSTER {settings.CLICKHOUSE_CLUSTER} AS (
    SELECT
        pd.team_id AS team_id,
        pd.distinct_id AS distinct_id,
        toString(p.id) AS person_id,
        p.properties AS properties,
        pd.version AS person_distinct_id_version,
        p.version AS person_version,
        multiIf(
            (pd._timestamp  >= {{interval_start:DateTime64}} AND pd._timestamp < {{interval_end:DateTime64}})
                AND NOT (p._timestamp >= {{interval_start:DateTime64}} AND p._timestamp < {{interval_end:DateTime64}}),
            pd._timestamp,
            (p._timestamp  >= {{interval_start:DateTime64}} AND p._timestamp < {{interval_end:DateTime64}})
                AND NOT (pd._timestamp >= {{interval_start:DateTime64}} AND pd._timestamp < {{interval_end:DateTime64}}),
            p._timestamp,
            least(p._timestamp, pd._timestamp)
        ) AS _inserted_at
    FROM (
        SELECT
            team_id,
            id,
            max(version) AS version,
            argMax(properties, person.version) AS properties,
            argMax(_timestamp, person.version) AS _timestamp
        FROM
            person
        PREWHERE
            team_id = {{team_id:Int64}}
        GROUP BY
            team_id,
            id
    ) AS p
    INNER JOIN (
        SELECT
            team_id,
            distinct_id,
            max(version) AS version,
            argMax(person_id, person_distinct_id2.version) AS person_id,
            argMax(_timestamp, person_distinct_id2.version) AS _timestamp
        FROM
            person_distinct_id2
        PREWHERE
            team_id = {{team_id:Int64}}
        GROUP BY
            team_id,
            distinct_id
    ) AS pd ON p.id = pd.person_id AND p.team_id = pd.team_id
    WHERE
        pd.team_id = {{team_id:Int64}}
        AND p.team_id = {{team_id:Int64}}
        AND ((pd._timestamp  >= {{interval_start:DateTime64}} AND pd._timestamp < {{interval_end:DateTime64}})
            OR (p._timestamp  >= {{interval_start:DateTime64}} AND p._timestamp < {{interval_end:DateTime64}}))
    ORDER BY
        _inserted_at
)
"""

CREATE_EVENTS_BATCH_EXPORT_VIEW = f"""
CREATE OR REPLACE VIEW events_batch_export ON CLUSTER {settings.CLICKHOUSE_CLUSTER} AS (
    SELECT DISTINCT ON (team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid))
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        COALESCE(inserted_at, _timestamp) AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        events
    PREWHERE
        events.inserted_at >= {{interval_start:DateTime64}}
        AND events.inserted_at < {{interval_end:DateTime64}}
    WHERE
        team_id = {{team_id:Int64}}
        AND events.timestamp >= {{interval_start:DateTime64}} - INTERVAL {{lookback_days:Int32}} DAY
        AND events.timestamp < {{interval_end:DateTime64}} + INTERVAL 1 DAY
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
    ORDER BY
        _inserted_at, event
    SETTINGS optimize_aggregation_in_order=1
)
"""

CREATE_EVENTS_BATCH_EXPORT_VIEW_UNBOUNDED = f"""
CREATE OR REPLACE VIEW events_batch_export_unbounded ON CLUSTER {settings.CLICKHOUSE_CLUSTER} AS (
    SELECT DISTINCT ON (team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid))
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        COALESCE(inserted_at, _timestamp) AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        events
    PREWHERE
        events.inserted_at >= {{interval_start:DateTime64}}
        AND events.inserted_at < {{interval_end:DateTime64}}
    WHERE
        team_id = {{team_id:Int64}}
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
    ORDER BY
        _inserted_at, event
    SETTINGS optimize_aggregation_in_order=1
)
"""

CREATE_EVENTS_BATCH_EXPORT_VIEW_BACKFILL = f"""
CREATE OR REPLACE VIEW events_batch_export_backfill ON CLUSTER {settings.CLICKHOUSE_CLUSTER} AS (
    SELECT DISTINCT ON (team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid))
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        COALESCE(inserted_at, _timestamp) AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        events
    WHERE
        team_id = {{team_id:Int64}}
        AND events.timestamp >= {{interval_start:DateTime64}}
        AND events.timestamp < {{interval_end:DateTime64}}
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
    ORDER BY
        _inserted_at, event
    SETTINGS optimize_aggregation_in_order=1
)
"""

# This view should be used to retry a past interval. The prewhere and where clauses are flipped. Check on all events in interval and then filter down
# to the events that have been inserted in later interval.
CREATE_EVENTS_BATCH_EXPORT_VIEW_BACKFILL_RERUN = f"""
CREATE OR REPLACE VIEW events_batch_export_backfill_rerun ON CLUSTER {settings.CLICKHOUSE_CLUSTER} AS (
    SELECT DISTINCT ON (team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid))
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        COALESCE(inserted_at, _timestamp) AS _inserted_at,
        created_at AS created_at,
        elements_chain AS elements_chain,
        toString(person_id) AS person_id,
        nullIf(properties, '') AS properties,
        nullIf(person_properties, '') AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        events
    PREWHERE
        events.timestamp >= {{interval_start:DateTime64}} - INTERVAL {{lookback_days:Int32}} DAY
        AND events.timestamp < {{interval_end:DateTime64}} + INTERVAL 1 DAY
    WHERE
        team_id = {{team_id:Int64}}
        AND events.inserted_at >= {{inserted_at_interval_start:DateTime64}}
        AND (length({{include_events:Array(String)}}) = 0 OR event IN {{include_events:Array(String)}})
        AND (length({{exclude_events:Array(String)}}) = 0 OR event NOT IN {{exclude_events:Array(String)}})
    ORDER BY
        _inserted_at, event
    SETTINGS optimize_aggregation_in_order=1
)
"""
