# Within PostHog, it is possible that two Persons are merged together. The
# impact of this is that all events that were associated with the Persons should
# now appear to be associated with a single Person.
#
# In the ClickHouse `sharded_events` table we have a `person_id` column that
# contains the UUID of the Person that the event is associated with. When a
# merge happens, we do not immediately update the `person_id` column in the
# `sharded_events` table. Instead, we create a new row in the `person_overrides`
# table that contains the mapping from the `old_person_id` to the
# `override_person_id`. This allows us to OUTER JOIN the `person_overrides`
# table to the `sharded_events` table to find all events that were associated
# and therefore reconcile the events to be associated with the same Person.

from posthog.kafka_client.topics import KAFKA_PERSON_OVERRIDE
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE, KAFKA_HOSTS

PERSON_OVERRIDES_CREATE_TABLE_SQL = f"""
    CREATE TABLE IF NOT EXISTS `{CLICKHOUSE_DATABASE}`.`person_overrides`
    ON CLUSTER '{CLICKHOUSE_CLUSTER}' (
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
        -- allow us to discard old mappings as new ones are added.
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
    ENGINE = ReplicatedReplacingMergeTree(
        '/clickhouse/tables/noshard/{CLICKHOUSE_DATABASE}.person_overrides',
        '{{replica}}-{{shard}}',
        version
    )

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
"""

# An abstraction over Kafka that allows us to consume, via a ClickHouse
# Materialized View from a Kafka topic and insert the messages into the
# ClickHouse MergeTree table `person_overrides`
PERSON_OVERRIDES_CREATE_KAFKA_TABLE_SQL = f"""
    CREATE TABLE IF NOT EXISTS `{CLICKHOUSE_DATABASE}`.`kafka_person_overrides`
    ON CLUSTER '{CLICKHOUSE_CLUSTER}'

    ENGINE = Kafka(
        '{KAFKA_HOSTS}', -- Kafka hosts
        '{KAFKA_PERSON_OVERRIDE}', -- Kafka topic
        'clickhouse-person-overrides', -- Kafka consumer group id
        'JSONEachRow' -- Specify that we should pass Kafka messages as JSON
    )

    -- We use the same schema as the `person_overrides` table except for columns
    -- that are set e.g. as defaults.
    EMPTY AS SELECT
        team_id,
        old_person_id,
        override_person_id,
        merged_at,
        -- created_at is not included in the Kafka message, rather it is set as
        -- a default in the MergeTree table
        version
    FROM `{CLICKHOUSE_DATABASE}`.`person_overrides`
"""

# Materialized View that watches the Kafka table for data and inserts into the
# `person_overrides` table.
PERSON_OVERRIDES_CREATE_MATERIALIZED_VIEW_SQL = f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS `{CLICKHOUSE_DATABASE}`.`person_overrides_mv`
    ON CLUSTER '{CLICKHOUSE_CLUSTER}'
    TO `{CLICKHOUSE_DATABASE}`.`person_overrides`
    AS SELECT *
    FROM `{CLICKHOUSE_DATABASE}`.`kafka_person_overrides`
"""
