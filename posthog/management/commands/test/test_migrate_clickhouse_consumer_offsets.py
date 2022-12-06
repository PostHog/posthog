from django.core.management import call_command
from kafka import KafkaProducer, OffsetAndMetadata

from posthog.kafka_client.client import KafkaAdminClient, TopicPartition, build_kafka_consumer

CLICKHOUSE_GROUP = "group1"
APP_METRICS_GROUP = "clickhouse-inserter-clickhouse_app_metrics"
APP_METRICS_TOPIC = "clickhouse_app_metrics"


def test_migrates_group1_offsets_to_new_consumer_group():
    """
    Make sure that the migration moves the offsets from the old group to the new
    group. It's a little tricky to test the migration as the infi migration
    doesn't offer a rollback method, and the migrations have already been
    applied by the time we run the tests. Otherwise, we would be able to use
    django.core.management.call_command to run a rollback then test the roll
    forward.

    Instead we only test the `migrate_consumer_group_offsets` method does what
    we expect.
    """

    kafka = KafkaAdminClient()
    producer = KafkaProducer()

    # First let's make sure that the consumer group offsets are not set.
    kafka.delete_consumer_groups(group_ids=[APP_METRICS_GROUP])
    # NOTE: the kafka-python library appears to get an error that it can't find
    # the group ID. However, it does appear to clear the offsets, so we
    # purposefully ignore the error.
    app_metrics_offsets = kafka.list_consumer_group_offsets(APP_METRICS_GROUP)
    assert len(app_metrics_offsets) == 0

    # As nothing has been pulled from via group1 yet, we need to add in some
    # offsets artificially to make sure we can actually test they are copied
    # over. We need to make sure there is one message in there such that we can
    # commit an offset.
    producer.send(APP_METRICS_TOPIC, b"test", key=b"test")
    consumer = build_kafka_consumer(topic=None, group_id="group1")
    consumer.commit(offsets={TopicPartition(APP_METRICS_TOPIC, 0): OffsetAndMetadata(offset=0, metadata={})})
    group1_group_offsets = kafka.list_consumer_group_offsets(CLICKHOUSE_GROUP)
    assert group1_group_offsets

    overlap = set(app_metrics_offsets.keys()) & set(group1_group_offsets.keys())
    assert len(overlap) == 0

    # Now that we have clarified that the offsets aren't set, let's run the
    # offset migration.
    call_command("migrate_clickhouse_consumer_offsets")

    app_metrics_offsets = kafka.list_consumer_group_offsets(APP_METRICS_GROUP)
    group1_group_offsets = kafka.list_consumer_group_offsets(CLICKHOUSE_GROUP)

    overlap = set(app_metrics_offsets.keys()) & set(group1_group_offsets.keys())
    assert overlap

    for topic_partition in overlap:
        assert app_metrics_offsets[topic_partition] == group1_group_offsets[topic_partition]

    # Also check that running the method again doesn't change anything.
    call_command("migrate_clickhouse_consumer_offsets")

    new_app_metrics_offsets = kafka.list_consumer_group_offsets(APP_METRICS_GROUP)
    assert new_app_metrics_offsets == app_metrics_offsets
