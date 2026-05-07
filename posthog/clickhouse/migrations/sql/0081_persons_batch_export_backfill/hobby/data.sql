CREATE OR REPLACE VIEW persons_batch_export_backfill ON CLUSTER posthog AS (
    SELECT
        pd.team_id AS team_id,
        pd.distinct_id AS distinct_id,
        toString(p.id) AS person_id,
        p.properties AS properties,
        pd.version AS person_distinct_id_version,
        p.version AS person_version,
        p.created_at AS created_at,
        multiIf(
            pd._timestamp < {interval_end:DateTime64}
                AND NOT p._timestamp < {interval_end:DateTime64},
            pd._timestamp,
            p._timestamp < {interval_end:DateTime64}
                AND NOT pd._timestamp < {interval_end:DateTime64},
            p._timestamp,
            least(p._timestamp, pd._timestamp)
        ) AS _inserted_at
    FROM (
        SELECT
            team_id,
            distinct_id,
            max(version) AS version,
            argMax(person_id, person_distinct_id2.version) AS person_id,
            argMax(_timestamp, person_distinct_id2.version) AS _timestamp
        FROM
            person_distinct_id2
        PREWHERE
            team_id = {team_id:Int64}
        GROUP BY
            team_id,
            distinct_id
    ) AS pd
    INNER JOIN (
        SELECT
            team_id,
            id,
            max(version) AS version,
            argMax(properties, person.version) AS properties,
            argMax(created_at, person.version) AS created_at,
            argMax(_timestamp, person.version) AS _timestamp
        FROM
            person
        PREWHERE
            team_id = {team_id:Int64}
        GROUP BY
            team_id,
            id
    ) AS p ON p.id = pd.person_id AND p.team_id = pd.team_id
    WHERE
        pd.team_id = {team_id:Int64}
        AND p.team_id = {team_id:Int64}
        AND (
            pd._timestamp < {interval_end:DateTime64}
            OR p._timestamp < {interval_end:DateTime64}
        )
    ORDER BY
        _inserted_at
)
