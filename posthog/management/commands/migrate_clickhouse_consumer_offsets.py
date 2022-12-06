import time

import structlog
from django.core.management.base import BaseCommand
from kafka import KafkaAdminClient

from posthog.kafka_client.client import build_kafka_consumer

logger = structlog.get_logger(__name__)


CLICKHOUSE_CONSUMER_GROUP = "group1"
TOPICS_TO_MIGRATE = [("clickhouse_app_metrics", "clickhouse-inserter-clickhouse_app_metrics")]


class Command(BaseCommand):
    help = "Migrate ClickHouse consumer group offsets."

    def add_arguments(self, parser):
        parser.add_argument("--fake", action="store_true", help="Mark migrations as run without actually running them.")
        parser.add_argument(
            "--check", action="store_true", help="Mark migrations as run without actually running them."
        )

    def handle(self, *args, **options):
        admin = KafkaAdminClient()

        for topic, group in TOPICS_TO_MIGRATE:
            migrate_clickhouse_consumer_group_for_topic(
                admin, CLICKHOUSE_CONSUMER_GROUP, group, topic, options["fake"], options["check"]
            )


def migrate_clickhouse_consumer_group_for_topic(
    admin: KafkaAdminClient, source_group: str, target_group: str, topic: str, fake: bool = False, check: bool = False
):
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
    logger.info("migrating_consumer_group", source_group=source_group, target_group=target_group, topic=topic)

    groups = admin.describe_consumer_groups([target_group])
    if len(groups) > 0:
        logger.info("consumer_group_exists", group=target_group)
        return
    elif check:
        logger.info("consumer_group_missing", group=target_group)
        exit(1)

    # Wait for no members of the consumer group to have subscribed to the
    # app_metrics topic
    for attempt in range(60):
        logger.info("waiting_for_no_topic_consumers", group=source_group, topic=topic, attempt=attempt)
        groups = admin.describe_consumer_groups([source_group])

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
        else:
            logger.info("group_has_members", group=source_group, members=app_metrics_topic_members)

        if attempt == 59:
            raise Exception("Consumer group still has members subscribed to app_metrics topic")

        time.sleep(1)

    all_offsets = admin.list_consumer_group_offsets(source_group)
    app_metrics_offsets = {
        topic_partition: offset for topic_partition, offset in all_offsets.items() if topic_partition.topic == topic
    }

    logger.info("creating_consumer_group", group=target_group, offsets=app_metrics_offsets, all_offsets=all_offsets)
    if not fake:
        consumer = build_kafka_consumer(topic=None, group_id=target_group)
        consumer.commit(offsets=app_metrics_offsets)
