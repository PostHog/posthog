from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.kafka_client.topics import KAFKA_PERSON_OVERRIDE
from posthog.settings.data_stores import CLICKHOUSE_DATABASE
from posthog.settings.kafka import KAFKA_HOSTS

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
