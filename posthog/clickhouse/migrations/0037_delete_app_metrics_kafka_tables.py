import structlog
from infi.clickhouse_orm import migrations

from posthog.kafka_client.client import KafkaAdminClient, build_kafka_consumer
from posthog.settings import CLICKHOUSE_CLUSTER

logger = structlog.get_logger(__name__)


def migrate_clickhouse_consumer_group_for_topic(source_group: str, target_group: str, topic: str):
    """
    This method is used as part of the removal of ClickHouse KafkaTables and
    migration to inserting from a Kafka consumer outside of the ClickHouse
    cluster instead. This should give us more control over how we consume, and
    simplify the dependency graph of the system.

    This method is used to migrate the offsets of one consumer group for a
    specific topic to a new consumer group that this method will create. This
    method will wait for the new consumer group to have no members before
    committing the offsets to the new consumer group, to minimise the number of
    duplicate rows that would be inserted into ClickHouse.
    """

    kafka = KafkaAdminClient()

    # Wait for no members of the consumer group to have subscribed to the
    # app_metrics topic
    for attempt in range(60):
        logger.info("waiting_for_no_topic_consumers", group=source_group, topic=topic, attempt=attempt)
        groups = kafka.describe_consumer_groups([source_group])

        # Check if the new consumer group already exists, and if so do not try
        # to set any offsets
        app_metrics_group = [group for group in groups if group.group == target_group]
        if len(app_metrics_group) > 0:
            logger.warn("consumer_group_exists", group=target_group)
            return

        clickhouse_consumer_group = [group for group in groups if group.group == source_group][0]
        app_metrics_topic_members = [
            member for member in clickhouse_consumer_group.members if topic in member.member_metadata.subscription
        ]

        if len(app_metrics_topic_members) == 0:
            logger.info("group_stable", group=source_group)
            break

        if attempt == 59:
            raise Exception("Consumer group still has members subscribed to app_metrics topic")

    all_offsets = kafka.list_consumer_group_offsets(source_group)
    app_metrics_offsets = {
        topic_partition: offset for topic_partition, offset in all_offsets.items() if topic_partition.topic == topic
    }

    logger.info("creating_consumer_group", group=target_group, offsets=app_metrics_offsets, all_offsets=all_offsets)
    consumer = build_kafka_consumer(topic=None, group_id=target_group)
    consumer.commit(offsets=app_metrics_offsets)


def migrate_consumer_group_offsets():
    CLICKHOUSE_CONSUMER_GROUP = "group1"
    APP_METRICS_GROUP = "clickhouse-inserter-app_metrics"
    APP_METRICS_TOPIC = "clickhouse_app_metrics"
    migrate_clickhouse_consumer_group_for_topic(CLICKHOUSE_CONSUMER_GROUP, APP_METRICS_GROUP, APP_METRICS_TOPIC)


operations = [
    # First we remove the Materialized View table and the KafkaTable
    migrations.RunSQL(f"DROP TABLE IF EXISTS app_metrics_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE IF EXISTS kafka_app_metrics ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    # Then we create a new consumer group with the same offsets as the old one
    # used by the KafkaTable we just deleted.
    migrations.RunPython(migrate_consumer_group_offsets),
]
