from infi.clickhouse_orm import migrations

from posthog.models.event.sql import DISTRIBUTED_EVENTS_TABLE_SQL, WRITABLE_EVENTS_TABLE_SQL
from posthog.models.person.sql import (
    KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL,
    KAFKA_PERSONS_TABLE_SQL,
    PERSONS_DISTINCT_ID_TABLE_MV_SQL,
    PERSONS_TABLE_MV_SQL,
)
from posthog.settings import CLICKHOUSE_REPLICATION

# NOTE: this migration previously created kafka_events and events_mv tables.
# kafka_events was a Kafka ClickHouse engine table that used Protobuf for
# serialization. To remove complexity of deployments, Protobuf support has been
# removed from the PostHog app and the Plugin server. See
# https://github.com/PostHog/posthog/issues/9207 for detail.
#
# These have been superseded by kafka_events_json and events_json_mv. However,
# we can't simply add a DROP TABLE for the old tables as there may still be
# events in Kafka that need to be consumed. We'd need some orchestration around
# this to avoid losing in flight events. See migration
# ee/clickhouse/migrations/0025_json_events.py for details of the new tables.
#
# For new installs however, we don't need to be consider this case, so we can
# simply not create them.
#
# WARNING: this does however mean that you can arrive at different DB states
# depending on which versions of PostHog you have run.
operations = [
    migrations.RunSQL(KAFKA_PERSONS_TABLE_SQL()),
    migrations.RunSQL(KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL()),
    migrations.RunSQL(PERSONS_TABLE_MV_SQL),
    migrations.RunSQL(PERSONS_DISTINCT_ID_TABLE_MV_SQL),
]

if CLICKHOUSE_REPLICATION:
    operations.extend(
        [migrations.RunSQL(WRITABLE_EVENTS_TABLE_SQL()), migrations.RunSQL(DISTRIBUTED_EVENTS_TABLE_SQL())]
    )
