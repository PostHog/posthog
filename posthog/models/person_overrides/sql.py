# XXX: The tables defined in this module are not used and are only retained for migration consistency reasons. See
# `person_distinct_id_overrides` in `posthog.models.person.sql` for its replacement tables, or
# https://github.com/PostHog/posthog/pull/23616 for additional context.

from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import ReplacingMergeTree, ReplicationScheme
from posthog.kafka_client.topics import KAFKA_PERSON_OVERRIDE
from posthog.settings.data_stores import CLICKHOUSE_DATABASE, KAFKA_HOSTS

PERSON_OVERRIDES_CREATE_TABLE_SQL = (
    lambda on_cluster=True: f"""
    CREATE TABLE IF NOT EXISTS `{CLICKHOUSE_DATABASE}`.`person_overrides`
    {ON_CLUSTER_CLAUSE(on_cluster)} (
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
    ENGINE = {{engine}}

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
""".format(
        engine=ReplacingMergeTree("person_overrides", replication_scheme=ReplicationScheme.REPLICATED, ver="version")
    )
)

# An abstraction over Kafka that allows us to consume, via a ClickHouse
# Materialized View from a Kafka topic and insert the messages into the
# ClickHouse MergeTree table `person_overrides`
KAFKA_PERSON_OVERRIDES_TABLE_SQL = f"""
    CREATE TABLE IF NOT EXISTS `{CLICKHOUSE_DATABASE}`.`kafka_person_overrides`
    {ON_CLUSTER_CLAUSE()}

    ENGINE = Kafka(
        '{",".join(KAFKA_HOSTS)}', -- Kafka hosts
        '{KAFKA_PERSON_OVERRIDE}', -- Kafka topic
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
    FROM `{CLICKHOUSE_DATABASE}`.`person_overrides`
"""

DROP_KAFKA_PERSON_OVERRIDES_TABLE_SQL = f"""
    DROP TABLE IF EXISTS `{CLICKHOUSE_DATABASE}`.`kafka_person_overrides`
    {ON_CLUSTER_CLAUSE()}
    SYNC
"""

# Materialized View that watches the Kafka table for data and inserts into the
# `person_overrides` table.
PERSON_OVERRIDES_CREATE_MATERIALIZED_VIEW_SQL = f"""
    CREATE MATERIALIZED VIEW IF NOT EXISTS `{CLICKHOUSE_DATABASE}`.`person_overrides_mv`
    {ON_CLUSTER_CLAUSE()}
    TO `{CLICKHOUSE_DATABASE}`.`person_overrides`
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
    FROM `{CLICKHOUSE_DATABASE}`.`kafka_person_overrides`
"""

DROP_PERSON_OVERRIDES_CREATE_MATERIALIZED_VIEW_SQL = f"""
    DROP VIEW IF EXISTS `{CLICKHOUSE_DATABASE}`.`person_overrides_mv`
    {ON_CLUSTER_CLAUSE()}
    SYNC
"""

GET_LATEST_PERSON_OVERRIDE_ID_SQL = f"""
SELECT
    team_id,
    old_person_id,
    argMax(override_person_id, version)
FROM
    `{CLICKHOUSE_DATABASE}`.`person_overrides` AS overrides
GROUP BY
    team_id,
    old_person_id
"""

# ClickHouse dictionaries allow us to JOIN events with their new override_person_ids (if any).
PERSON_OVERRIDES_CREATE_DICTIONARY_SQL = f"""
    CREATE DICTIONARY IF NOT EXISTS `{CLICKHOUSE_DATABASE}`.`person_overrides_dict`
    {ON_CLUSTER_CLAUSE()} (
        team_id INT,
        old_person_id UUID,
        override_person_id UUID
    )
    PRIMARY KEY team_id, old_person_id
    SOURCE(CLICKHOUSE(QUERY '{GET_LATEST_PERSON_OVERRIDE_ID_SQL}'))
    LAYOUT(COMPLEX_KEY_HASHED(PREALLOCATE 1))

    -- The LIFETIME setting indicates to ClickHouse to automatically update this dictionary
    -- when not set to 0. When using a time range ClickHouse will pick a uniformly random time in
    -- the range. We are setting an initial update time range of 5 to 10 seconds.
    LIFETIME(MIN 5 MAX 10)
"""

DROP_PERSON_OVERRIDES_CREATE_DICTIONARY_SQL = f"""
    DROP DICTIONARY IF EXISTS `{CLICKHOUSE_DATABASE}`.`person_overrides_dict`
    {ON_CLUSTER_CLAUSE()}
"""
