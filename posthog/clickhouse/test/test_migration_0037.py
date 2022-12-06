import importlib

from django.conf import settings
from infi.clickhouse_orm import Database

from posthog.kafka_client.client import KafkaAdminClient

migration = importlib.import_module("posthog.clickhouse.migrations.0037_delete_app_metrics_kafka_tables")

CLICKHOUSE_GROUP = "group1"
APP_METRICS_GROUP = "clickhouse-inserter-app_metrics"
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
    database = Database(
        settings.CLICKHOUSE_DATABASE,
        db_url=settings.CLICKHOUSE_HTTP_URL,
        username=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        cluster=settings.CLICKHOUSE_CLUSTER,
        verify_ssl_cert=False,
    )

    # First let's make sure that the consumer group offsets are not set.
    kafka.delete_consumer_groups(group_ids=[APP_METRICS_GROUP])
    # NOTE: the kafka-python library appears to get an error that it can't find
    # the group ID. However, it does appear to clear the offsets, so we
    # purposefully ignore the error.
    app_metrics_offsets = kafka.list_consumer_group_offsets(APP_METRICS_GROUP)
    assert len(app_metrics_offsets) == 0

    group1_group_offsets = kafka.list_consumer_group_offsets(CLICKHOUSE_GROUP)
    assert group1_group_offsets

    overlap = set(app_metrics_offsets.keys()) & set(group1_group_offsets.keys())
    assert len(overlap) == 0

    # Now that we have clarified that the offsets aren't set, let's run the
    # offset migration.
    migration.migrate_consumer_group_offsets(database)

    app_metrics_offsets = kafka.list_consumer_group_offsets(APP_METRICS_GROUP)
    group1_group_offsets = kafka.list_consumer_group_offsets(CLICKHOUSE_GROUP)

    overlap = set(app_metrics_offsets.keys()) & set(group1_group_offsets.keys())
    assert overlap

    for topic_partition in overlap:
        assert app_metrics_offsets[topic_partition] == group1_group_offsets[topic_partition]

    # Also check that running the method again doesn't change anything.
    migration.migrate_consumer_group_offsets(database)

    new_app_metrics_offsets = kafka.list_consumer_group_offsets(APP_METRICS_GROUP)
    assert new_app_metrics_offsets == app_metrics_offsets
