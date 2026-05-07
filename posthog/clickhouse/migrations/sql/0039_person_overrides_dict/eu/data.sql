CREATE DICTIONARY IF NOT EXISTS `default`.`person_overrides_dict`
    ON CLUSTER 'posthog' (
        team_id INT,
        old_person_id UUID,
        override_person_id UUID
    )
    PRIMARY KEY team_id, old_person_id
    SOURCE(CLICKHOUSE(QUERY '
SELECT
    team_id,
    old_person_id,
    argMax(override_person_id, version)
FROM
    `default`.`person_overrides` AS overrides
GROUP BY
    team_id,
    old_person_id
'))
    LAYOUT(COMPLEX_KEY_HASHED(PREALLOCATE 1))

    -- The LIFETIME setting indicates to ClickHouse to automatically update this dictionary
    -- when not set to 0. When using a time range ClickHouse will pick a uniformly random time in
    -- the range. We are setting an initial update time range of 5 to 10 seconds.
    LIFETIME(MIN 5 MAX 10)
