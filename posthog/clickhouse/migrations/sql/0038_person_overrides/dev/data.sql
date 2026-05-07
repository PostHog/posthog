CREATE TABLE IF NOT EXISTS `default`.`person_overrides`
    ON CLUSTER 'posthog' (
        team_id INT NOT NULL,

        -- When we merge two people `old_person_id` and `override_person_id`, we
        -- want to keep track of a mapping from the `old_person_id` to the
        -- `override_person_id`. This allows us to join with the
        -- `sharded_events` table to find all events that were associated with
        -- the `old_person_id` and update them to be associated with the
        -- `override_person_id`.
        old_person_id UUID NOT NULL,
        override_person_id UUID NOT NULL,

        -- The timestamp the merge of the two people was completed.
        merged_at DateTime64(6, 'UTC') NOT NULL,
        -- The timestamp of the oldest event associated with the
        -- `old_person_id`.
        oldest_event DateTime64(6, 'UTC') NOT NULL,
        -- The timestamp rows are created. This isn't part of the JOIN process
        -- with the events table but rather a housekeeping column to allow us to
        -- see when the row was created. This shouldn't have any impact of the
        -- JOIN as it will be stored separately with the Wide ClickHouse table
        -- storage.
        created_at DateTime64(6, 'UTC') DEFAULT now(),

        -- the specific version of the `old_person_id` mapping. This is used to
        -- allow us to discard old mappings as new ones are added. This version
        -- will be provided by the corresponding PostgreSQL
        --`posthog_personoverrides` table
        version INT NOT NULL
    )

    -- By specifying Replacing merge tree on version, we allow ClickHouse to
    -- discard old versions of a `old_person_id` mapping. This should help keep
    -- performance in check as new versions are added. Note that given we can
    -- have partitioning by `oldest_event` which will change as we update
    -- `person_id` on old partitions.
    --
    -- We also need to ensure that the data is replicated to all replicas in the
    -- cluster, as we do not have any constraints on person_id and which shard
    -- associated events are on. To do this we use the ReplicatedReplacingMergeTree
    -- engine specifying a static `zk_path`. This will cause the Engine to
    -- consider all replicas as the same. See
    -- https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/replication
    -- for details.
    ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.person_overrides', '{replica}-{shard}', version)

    -- We partition the table by the `oldest_event` column. This allows us to
    -- handle updating the events table partition by partition, progressing each
    -- override partition by partition in lockstep with the events table. Note
    -- that this means it is possible that we have a mapping from
    -- `old_person_id` in multiple partitions during the merge process.
    PARTITION BY toYYYYMM(oldest_event)

    -- We want to collapse down on the `old_person_id` such that we end up with
    -- the newest known mapping for it in the table. Query side we will need to
    -- ensure that we are always querying the latest version of the mapping.
    ORDER BY (team_id, old_person_id)

CREATE TABLE IF NOT EXISTS `default`.`kafka_person_overrides`
    ON CLUSTER 'posthog'

    ENGINE = Kafka(
        'kafka:9092', -- Kafka hosts
        'clickhouse_person_override', -- Kafka topic
        'clickhouse-person-overrides', -- Kafka consumer group id
        'JSONEachRow' -- Specify that we should pass Kafka messages as JSON
    )

    -- Take the types from the `person_overrides` table, except for the
    -- `created_at`, which we want to use the DEFAULT now() from the
    -- `person_overrides` definition. See
    -- https://github.com/ClickHouse/ClickHouse/pull/38272 for details of `EMPTY
    -- AS SELECT`
    EMPTY AS SELECT
        team_id,
        old_person_id,
        override_person_id,
        merged_at,
        oldest_event,
        -- We don't want to insert this column via Kafka, as it's
        -- set as a default value in the `person_overrides` table.
        -- created_at,
        version
    FROM `default`.`person_overrides`

CREATE MATERIALIZED VIEW IF NOT EXISTS `default`.`person_overrides_mv`
    ON CLUSTER 'posthog'
    TO `default`.`person_overrides`
    AS SELECT
        team_id,
        old_person_id,
        override_person_id,
        merged_at,
        oldest_event,
        -- We don't want to insert this column via Kafka, as it's
        -- set as a default value in the `person_overrides` table.
        -- created_at,
        version
    FROM `default`.`kafka_person_overrides`
