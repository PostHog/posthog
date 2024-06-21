CREATE_PERSONS_BATCH_EXPORT_VIEW = """
CREATE OR REPLACE VIEW persons_batch_export AS (
    SELECT
        pd.team_id AS team_id,
        pd.distinct_id AS distinct_id,
        toString(p.id) AS person_id,
        p.properties AS properties,
        pd.version AS version,
        pd._timestamp AS _inserted_at
    FROM (
        SELECT
            team_id,
            distinct_id,
            max(version) AS version,
            argMax(person_id, person_distinct_id2.version) AS person_id,
            max(_timestamp) AS _timestamp
        FROM
            person_distinct_id2
        WHERE
            team_id = {team_id:Int64}
        GROUP BY
            team_id,
            distinct_id
    ) AS pd
    INNER JOIN
        person p ON p.id = pd.person_id AND p.team_id = pd.team_id
    WHERE
        pd.team_id = {team_id:Int64}
        AND p.team_id = {team_id:Int64}
        AND pd._timestamp >= {interval_start:DateTime64}
        AND pd._timestamp < {interval_end:DateTime64}
    ORDER BY
        _inserted_at
)
"""

CREATE_EVENTS_BATCH_EXPORT_VIEW = """
CREATE OR REPLACE VIEW events_batch_export AS (
    SELECT
        team_id AS team_id,
        min(timestamp) AS timestamp,
        event AS event,
        any(distinct_id) AS distinct_id,
        any(toString(uuid)) AS uuid,
        min(COALESCE(inserted_at, _timestamp)) AS _inserted_at,
        any(created_at) AS created_at,
        any(elements_chain) AS elements_chain,
        any(toString(person_id)) AS person_id,
        any(nullIf(properties, '')) AS properties,
        any(nullIf(person_properties, '')) AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        events
    PREWHERE
        events.inserted_at >= {interval_start:DateTime64}
        AND events.inserted_at < {interval_end:DateTime64}
    WHERE
        team_id = {team_id:Int64}
        AND events.timestamp >= {interval_start:DateTime64} - INTERVAL {lookback_days:Int32} DAY
        AND events.timestamp < {interval_end:DateTime64} + INTERVAL 1 DAY
        AND (length({include_events:Array(String)}) = 0 OR event IN {include_events:Array(String)})
        AND (length({exclude_events:Array(String)}) = 0 OR event NOT IN {exclude_events:Array(String)})
    GROUP BY
        team_id, toDate(events.timestamp), event, cityHash64(events.distinct_id), cityHash64(events.uuid)
    ORDER BY
        _inserted_at, event
    SETTINGS optimize_aggregation_in_order=1
)
"""

CREATE_EVENTS_BATCH_EXPORT_VIEW_UNBOUNDED = """
CREATE OR REPLACE VIEW events_batch_export_unbounded AS (
    SELECT
        team_id AS team_id,
        min(timestamp) AS timestamp,
        event AS event,
        any(distinct_id) AS distinct_id,
        any(toString(uuid)) AS uuid,
        min(COALESCE(inserted_at, _timestamp)) AS _inserted_at,
        any(created_at) AS created_at,
        any(elements_chain) AS elements_chain,
        any(toString(person_id)) AS person_id,
        any(nullIf(properties, '')) AS properties,
        any(nullIf(person_properties, '')) AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        events
    PREWHERE
        events.inserted_at >= {interval_start:DateTime64}
        AND events.inserted_at < {interval_end:DateTime64}
    WHERE
        team_id = {team_id:Int64}
        AND (length({include_events:Array(String)}) = 0 OR event IN {include_events:Array(String)})
        AND (length({exclude_events:Array(String)}) = 0 OR event NOT IN {exclude_events:Array(String)})
    GROUP BY
        team_id, toDate(events.timestamp), event, cityHash64(events.distinct_id), cityHash64(events.uuid)
    ORDER BY
        _inserted_at, event
    SETTINGS optimize_aggregation_in_order=1
)
"""

CREATE_EVENTS_BATCH_EXPORT_VIEW_BACKFILL = """
CREATE OR REPLACE VIEW events_batch_export_backfill AS (
    SELECT
        team_id AS team_id,
        min(timestamp) AS timestamp,
        event AS event,
        any(distinct_id) AS distinct_id,
        any(toString(uuid)) AS uuid,
        min(COALESCE(inserted_at, _timestamp)) AS _inserted_at,
        any(created_at) AS created_at,
        any(elements_chain) AS elements_chain,
        any(toString(person_id)) AS person_id,
        any(nullIf(properties, '')) AS properties,
        any(nullIf(person_properties, '')) AS person_properties,
        nullIf(JSONExtractString(properties, '$set'), '') AS set,
        nullIf(JSONExtractString(properties, '$set_once'), '') AS set_once
    FROM
        events
    WHERE
        team_id = {team_id:Int64}
        AND events.timestamp >= {interval_start:DateTime64}
        AND events.timestamp < {interval_end:DateTime64}
        AND (length({include_events:Array(String)}) = 0 OR event IN {include_events:Array(String)})
        AND (length({exclude_events:Array(String)}) = 0 OR event NOT IN {exclude_events:Array(String)})
    GROUP BY
        team_id, toDate(events.timestamp), event, cityHash64(events.distinct_id), cityHash64(events.uuid)
    ORDER BY
        _inserted_at, event
    SETTINGS optimize_aggregation_in_order=1
)
"""
