CREATE OR REPLACE VIEW persons_batch_export ON CLUSTER posthog AS (
    with new_persons as (
        select
            id,
            max(version) as version,
            argMax(_timestamp, person.version) AS _timestamp2
        from
            person
        where
            team_id = {team_id:Int64}
            and id in (
                select
                    id
                from
                    person
                where
                    team_id = {team_id:Int64}
                    and _timestamp >= {interval_start:DateTime64}
                    AND _timestamp < {interval_end:DateTime64}
            )
        group by
            id
        having
            (
                _timestamp2 >= {interval_start:DateTime64}
                AND _timestamp2 < {interval_end:DateTime64}
            )
    ),
    new_distinct_ids as (
        SELECT
            argMax(person_id, person_distinct_id2.version) as person_id
        from
            person_distinct_id2
        where
            team_id = {team_id:Int64}
            and distinct_id in (
                select
                    distinct_id
                from
                    person_distinct_id2
                where
                    team_id = {team_id:Int64}
                    and _timestamp >= {interval_start:DateTime64}
                    AND _timestamp < {interval_end:DateTime64}
            )
        group by
            distinct_id
        having
            (
                argMax(_timestamp, person_distinct_id2.version) >= {interval_start:DateTime64}
                AND argMax(_timestamp, person_distinct_id2.version) < {interval_end:DateTime64}
            )
    ),
    all_new_persons as (
        select
            id,
            version
        from
            new_persons
        UNION
        ALL
        select
            id,
            max(version)
        from
            person
        where
            team_id = {team_id:Int64}
            and id in new_distinct_ids
        group by
            id
    )
    select
        p.team_id AS team_id,
        pd.distinct_id AS distinct_id,
        toString(p.id) AS person_id,
        p.properties AS properties,
        pd.version AS person_distinct_id_version,
        p.version AS person_version,
        p.created_at AS created_at,
        multiIf(
            (
                pd._timestamp >= {interval_start:DateTime64}
                AND pd._timestamp < {interval_end:DateTime64}
            )
            AND NOT (
                p._timestamp >= {interval_start:DateTime64}
                AND p._timestamp < {interval_end:DateTime64}
            ),
            pd._timestamp,
            (
                p._timestamp >= {interval_start:DateTime64}
                AND p._timestamp < {interval_end:DateTime64}
            )
            AND NOT (
                pd._timestamp >= {interval_start:DateTime64}
                AND pd._timestamp < {interval_end:DateTime64}
            ),
            p._timestamp,
            least(p._timestamp, pd._timestamp)
        ) AS _inserted_at
    from
        person p
        INNER JOIN (
            SELECT
                distinct_id,
                max(version) AS version,
                argMax(person_id, person_distinct_id2.version) AS person_id2,
                argMax(_timestamp, person_distinct_id2.version) AS _timestamp
            FROM
                person_distinct_id2
            WHERE
                team_id = {team_id:Int64}
                and person_id IN (
                    select
                        id
                    from
                        all_new_persons
                )
            GROUP BY
                distinct_id
        ) AS pd ON p.id = pd.person_id2
    where
        team_id = {team_id:Int64}
        and (id, version) in all_new_persons
    ORDER BY
        _inserted_at
)

CREATE OR REPLACE VIEW events_batch_export ON CLUSTER posthog AS (
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
        COALESCE(events.inserted_at, events._timestamp) >= {interval_start:DateTime64}
        AND COALESCE(events.inserted_at, events._timestamp) < {interval_end:DateTime64}
    WHERE
        team_id = {team_id:Int64}
        AND events.timestamp >= {interval_start:DateTime64} - INTERVAL {lookback_days:Int32} DAY
        AND events.timestamp < {interval_end:DateTime64} + INTERVAL 1 DAY
        AND (length({include_events:Array(String)}) = 0 OR event IN {include_events:Array(String)})
        AND (length({exclude_events:Array(String)}) = 0 OR event NOT IN {exclude_events:Array(String)})
    ORDER BY
        _inserted_at, event
    SETTINGS optimize_aggregation_in_order=1
)

CREATE OR REPLACE VIEW events_batch_export_unbounded ON CLUSTER posthog AS (
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
        COALESCE(events.inserted_at, events._timestamp) >= {interval_start:DateTime64}
        AND COALESCE(events.inserted_at, events._timestamp) < {interval_end:DateTime64}
    WHERE
        team_id = {team_id:Int64}
        AND (length({include_events:Array(String)}) = 0 OR event IN {include_events:Array(String)})
        AND (length({exclude_events:Array(String)}) = 0 OR event NOT IN {exclude_events:Array(String)})
    ORDER BY
        _inserted_at, event
    SETTINGS optimize_aggregation_in_order=1
)

CREATE OR REPLACE VIEW events_batch_export_backfill ON CLUSTER posthog AS (
    SELECT DISTINCT ON (team_id, event, cityHash64(events.distinct_id), cityHash64(events.uuid))
        team_id AS team_id,
        timestamp AS timestamp,
        event AS event,
        distinct_id AS distinct_id,
        toString(uuid) AS uuid,
        timestamp AS _inserted_at,
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
        team_id = {team_id:Int64}
        AND events.timestamp >= {interval_start:DateTime64}
        AND events.timestamp < {interval_end:DateTime64}
        AND (length({include_events:Array(String)}) = 0 OR event IN {include_events:Array(String)})
        AND (length({exclude_events:Array(String)}) = 0 OR event NOT IN {exclude_events:Array(String)})
    ORDER BY
        _inserted_at, event
    SETTINGS optimize_aggregation_in_order=1
)
