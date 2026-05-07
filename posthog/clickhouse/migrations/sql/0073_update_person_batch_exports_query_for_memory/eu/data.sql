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
