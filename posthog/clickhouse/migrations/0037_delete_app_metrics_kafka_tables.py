import structlog
from infi.clickhouse_orm import migrations

from posthog.kafka_client.client import KafkaAdminClient, build_kafka_consumer
from posthog.settings import CLICKHOUSE_CLUSTER

logger = structlog.get_logger(__name__)


def create_new_consumer_group(database):
    # This is the consumer group ClickHouse KafkaTables currently use.
    CLICKHOUSE_CONSUMER_GROUP = "group1"
    APP_METRICS_GROUP = "clickhouse-inserter-app_metrics"
    APP_METRICS_TOPIC = "app_metrics"

    kafka = KafkaAdminClient()

    # Wait for no members of the consumer group to have subscribed to the
    # app_metrics topic
    for attempt in range(60):
        logger.info(
            "waiting_for_no_topic_consumers", group=CLICKHOUSE_CONSUMER_GROUP, topic=APP_METRICS_TOPIC, attempt=attempt
        )
        groups = kafka.describe_consumer_groups([CLICKHOUSE_CONSUMER_GROUP])

        # Check if the new consumer group already exists, and if so do not try
        # to set any offsets
        app_metrics_group = [group for group in groups if group.group == APP_METRICS_GROUP]
        if len(app_metrics_group) > 0:
            logger.warn("consumer_group_exists", group=APP_METRICS_GROUP)
            return

        clickhouse_consumer_group = [group for group in groups if group.group == CLICKHOUSE_CONSUMER_GROUP][0]
        app_metrics_topic_members = [
            member
            for member in clickhouse_consumer_group.members
            if APP_METRICS_TOPIC in member.member_metadata.subscription
        ]

        if len(app_metrics_topic_members) == 0:
            logger.info("group_stable", group=CLICKHOUSE_CONSUMER_GROUP)
            break

        if attempt == 59:
            raise Exception("Consumer group still has members subscribed to app_metrics topic")

    all_offsets = kafka.list_consumer_group_offsets(CLICKHOUSE_CONSUMER_GROUP)
    app_metrics_offsets = {
        topic_partition: offset
        for topic_partition, offset in all_offsets.items()
        if topic_partition.topic == APP_METRICS_TOPIC
    }

    logger.info("creating_consumer_group", group=APP_METRICS_GROUP, offsets=app_metrics_offsets)
    consumer = build_kafka_consumer(topic=None, group_id="clickhouse-inserter-app_metrics")
    consumer.commit(offsets=app_metrics_offsets)


operations = [
    # First we remove the Materialized View table and the KafkaTable
    migrations.RunSQL(f"DROP TABLE IF EXISTS app_metrics_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    migrations.RunSQL(f"DROP TABLE IF EXISTS kafka_app_metrics ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    # Then we create a new consumer group with the same offsets as the old one
    # used by the KafkaTable we just deleted.
    migrations.RunPython(create_new_consumer_group),
]
