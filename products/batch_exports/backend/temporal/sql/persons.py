"""SQL for the persons batch export model."""

from string import Template

SELECT_FROM_PERSONS = """
SELECT
    persons.team_id AS team_id,
    persons.distinct_id AS distinct_id,
    persons.person_id AS person_id,
    persons.properties AS properties,
    persons.person_distinct_id_version AS person_distinct_id_version,
    persons.person_version AS person_version,
    persons.created_at AS created_at,
    persons._inserted_at AS _inserted_at,
    persons.is_deleted AS is_deleted
FROM (
    WITH new_persons AS (
        SELECT
            id
        FROM
            person
        WHERE
            team_id = {team_id}::Int64
            AND id in (
                SELECT
                    id
                FROM
                    person
                WHERE
                    team_id = {team_id}::Int64
                    AND _timestamp >= {interval_start}::DateTime64
                    AND _timestamp < {interval_end}::DateTime64
            )
        GROUP BY
            id
        HAVING
            argMax(_timestamp, person.version) >= {interval_start}::DateTime64
            AND argMax(_timestamp, person.version) < {interval_end}::DateTime64
    ),
    distinct_ids AS (
        -- new distinct_ids
        SELECT
            distinct_id
        FROM
            person_distinct_id2
        WHERE
            team_id = {team_id}::Int64
            AND distinct_id in (
                SELECT
                    distinct_id
                FROM
                    person_distinct_id2
                WHERE
                    team_id = {team_id}::Int64
                    AND _timestamp >= {interval_start}::DateTime64
                    AND _timestamp < {interval_end}::DateTime64
            )
        GROUP BY
            distinct_id
        HAVING
            argMax(_timestamp, person_distinct_id2.version) >= {interval_start}::DateTime64
            AND argMax(_timestamp, person_distinct_id2.version) < {interval_end}::DateTime64

        UNION DISTINCT

        -- existing distinct_ids for new/updated persons
        SELECT
            DISTINCT distinct_id
        FROM
            person_distinct_id2
        WHERE
            team_id = {team_id}::Int64
            AND person_id IN new_persons
    ),
    latest_distinct_ids AS (
        SELECT
            distinct_id,
            argMax(person_id, person_distinct_id2.version) AS person_id2,
            max(version) AS version,
            argMax(_timestamp, person_distinct_id2.version) AS _timestamp
        FROM
            person_distinct_id2
        WHERE
            team_id = {team_id}::Int64
            AND distinct_id IN distinct_ids
        GROUP BY
            distinct_id
    ),
    latest_person_versions AS (
        SELECT
            id,
            max(version) AS version,
            max(_timestamp) AS _timestamp
        FROM
            person
        WHERE
            team_id = {team_id}::Int64
            AND
            id IN (
                SELECT
                    DISTINCT person_id2
                FROM
                    latest_distinct_ids
            )
        GROUP BY
            id
    )
    SELECT
        p.team_id AS team_id,
        pd.distinct_id AS distinct_id,
        toString(pd.person_id2) AS person_id,
        p.version AS person_version,
        pd.version AS person_distinct_id_version,
        p.properties AS properties,
        p.created_at AS created_at,
        toBool(p.is_deleted) AS is_deleted,
        multiIf(
            (
                pd._timestamp >= {interval_start}::DateTime64
                AND pd._timestamp < {interval_end}::DateTime64
            )
            AND NOT (
                p._timestamp >= {interval_start}::DateTime64
                AND p._timestamp < {interval_end}::DateTime64
            ),
            pd._timestamp,
            (
                p._timestamp >= {interval_start}::DateTime64
                AND p._timestamp < {interval_end}::DateTime64
            )
            AND NOT (
                pd._timestamp >= {interval_start}::DateTime64
                AND pd._timestamp < {interval_end}::DateTime64
            ),
            p._timestamp,
            least(p._timestamp, pd._timestamp)
        ) AS _inserted_at
    FROM
        person p
        INNER JOIN latest_distinct_ids pd
            ON p.id = pd.person_id2
    WHERE
        p.team_id = {team_id}::Int64
        AND (p.id, p.version, p._timestamp) in latest_person_versions
    ORDER BY
        _inserted_at
) AS persons
FORMAT ArrowStream
SETTINGS
    max_bytes_before_external_group_by=50000000000,
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""


EXPORT_TO_S3_FROM_PERSONS = Template("""
INSERT INTO FUNCTION $s3_function
SELECT
    persons.team_id AS team_id,
    persons.distinct_id AS distinct_id,
    persons.person_id AS person_id,
    persons.properties AS properties,
    persons.person_distinct_id_version AS person_distinct_id_version,
    persons.person_version AS person_version,
    persons.created_at AS created_at,
    persons._inserted_at AS _inserted_at,
    persons.is_deleted AS is_deleted
FROM (
    WITH new_persons AS (
        SELECT
            id
        FROM
            person
        WHERE
            team_id = {team_id}::Int64
            AND id in (
                SELECT
                    id
                FROM
                    person
                WHERE
                    team_id = {team_id}::Int64
                    AND _timestamp >= {interval_start}::DateTime64
                    AND _timestamp < {interval_end}::DateTime64
            )
        GROUP BY
            id
        HAVING
            argMax(_timestamp, person.version) >= {interval_start}::DateTime64
            AND argMax(_timestamp, person.version) < {interval_end}::DateTime64
    ),
    distinct_ids AS (
        -- new distinct_ids
        SELECT
            distinct_id
        FROM
            person_distinct_id2
        WHERE
            team_id = {team_id}::Int64
            AND distinct_id in (
                SELECT
                    distinct_id
                FROM
                    person_distinct_id2
                WHERE
                    team_id = {team_id}::Int64
                    AND _timestamp >= {interval_start}::DateTime64
                    AND _timestamp < {interval_end}::DateTime64
            )
        GROUP BY
            distinct_id
        HAVING
            argMax(_timestamp, person_distinct_id2.version) >= {interval_start}::DateTime64
            AND argMax(_timestamp, person_distinct_id2.version) < {interval_end}::DateTime64

        UNION DISTINCT

        -- existing distinct_ids for new/updated persons
        SELECT
            DISTINCT distinct_id
        FROM
            person_distinct_id2
        WHERE
            team_id = {team_id}::Int64
            AND person_id IN new_persons
    ),
    latest_distinct_ids AS (
        SELECT
            distinct_id,
            argMax(person_id, person_distinct_id2.version) AS person_id2,
            max(version) AS version,
            argMax(_timestamp, person_distinct_id2.version) AS _timestamp
        FROM
            person_distinct_id2
        WHERE
            team_id = {team_id}::Int64
            AND distinct_id IN distinct_ids
        GROUP BY
            distinct_id
        $filter_distinct_ids
    ),
    latest_person_versions AS (
        SELECT
            id,
            max(version) AS version,
            max(_timestamp) AS _timestamp
        FROM
            person
        WHERE
            team_id = {team_id}::Int64
            AND
            id IN (
                SELECT
                    DISTINCT person_id2
                FROM
                    latest_distinct_ids
            )
        GROUP BY
            id
    )
    SELECT
        p.team_id AS team_id,
        pd.distinct_id AS distinct_id,
        toString(pd.person_id2) AS person_id,
        p.version AS person_version,
        pd.version AS person_distinct_id_version,
        p.properties AS properties,
        p.created_at AS created_at,
        toBool(p.is_deleted) AS is_deleted,
        multiIf(
            (
                pd._timestamp >= {interval_start}::DateTime64
                AND pd._timestamp < {interval_end}::DateTime64
            )
            AND NOT (
                p._timestamp >= {interval_start}::DateTime64
                AND p._timestamp < {interval_end}::DateTime64
            ),
            pd._timestamp,
            (
                p._timestamp >= {interval_start}::DateTime64
                AND p._timestamp < {interval_end}::DateTime64
            )
            AND NOT (
                pd._timestamp >= {interval_start}::DateTime64
                AND pd._timestamp < {interval_end}::DateTime64
            ),
            p._timestamp,
            least(p._timestamp, pd._timestamp)
        ) AS _inserted_at
    FROM
        person p
        INNER JOIN latest_distinct_ids pd
            ON p.id = pd.person_id2
    WHERE
        p.team_id = {team_id}::Int64
        AND (p.id, p.version, p._timestamp) in latest_person_versions
) AS persons
SETTINGS
    max_bytes_before_external_group_by=50000000000,
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1,
    log_comment={log_comment}
""")


SELECT_FROM_PERSONS_BACKFILL = """
SELECT
    pd.team_id AS team_id,
    pd.distinct_id AS distinct_id,
    toString(p.id) AS person_id,
    p.properties AS properties,
    pd.version AS person_distinct_id_version,
    p.version AS person_version,
    p.created_at AS created_at,
    toBool(p.is_deleted) AS is_deleted,
    multiIf(
        pd._timestamp < {interval_end}::DateTime64
            AND NOT p._timestamp < {interval_end}::DateTime64,
        pd._timestamp,
        p._timestamp < {interval_end}::DateTime64
            AND NOT pd._timestamp < {interval_end}::DateTime64,
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
        team_id = {team_id}::Int64
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
        argMax(_timestamp, person.version) AS _timestamp,
        argMax(is_deleted, person.version) AS is_deleted
    FROM
        person
    PREWHERE
        team_id = {team_id}::Int64
    GROUP BY
        team_id,
        id
) AS p ON p.id = pd.person_id AND p.team_id = pd.team_id
WHERE
    pd.team_id = {team_id}::Int64
    AND p.team_id = {team_id}::Int64
    AND (
        pd._timestamp < {interval_end}::DateTime64
        OR p._timestamp < {interval_end}::DateTime64
    )
ORDER BY
    _inserted_at
FORMAT ArrowStream
SETTINGS
    max_bytes_before_external_group_by=50000000000,
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1
"""


EXPORT_TO_S3_FROM_PERSONS_BACKFILL = Template("""
INSERT INTO FUNCTION $s3_function
SELECT
    pd.team_id AS team_id,
    pd.distinct_id AS distinct_id,
    toString(p.id) AS person_id,
    p.properties AS properties,
    pd.version AS person_distinct_id_version,
    p.version AS person_version,
    p.created_at AS created_at,
    toBool(p.is_deleted) AS is_deleted,
    multiIf(
        pd._timestamp < {interval_end}::DateTime64
            AND NOT p._timestamp < {interval_end}::DateTime64,
        pd._timestamp,
        p._timestamp < {interval_end}::DateTime64
            AND NOT pd._timestamp < {interval_end}::DateTime64,
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
        team_id = {team_id}::Int64
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
        argMax(_timestamp, person.version) AS _timestamp,
        argMax(is_deleted, person.version) AS is_deleted
    FROM
        person
    PREWHERE
        team_id = {team_id}::Int64
    GROUP BY
        team_id,
        id
) AS p ON p.id = pd.person_id AND p.team_id = pd.team_id
WHERE
    pd.team_id = {team_id}::Int64
    AND p.team_id = {team_id}::Int64
    AND (
        pd._timestamp < {interval_end}::DateTime64
        OR p._timestamp < {interval_end}::DateTime64
    )
SETTINGS
    max_bytes_before_external_group_by=50000000000,
    max_bytes_before_external_sort=50000000000,
    optimize_aggregation_in_order=1,
    log_comment={log_comment}
""")
