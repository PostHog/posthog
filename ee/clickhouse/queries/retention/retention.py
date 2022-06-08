from ee.clickhouse.queries.retention.retention_actors import (
    ClickhouseRetentionActors,
    ClickhouseRetentionActorsByPeriod,
)
from ee.clickhouse.queries.retention.retention_event_query import ClickhouseRetentionEventsQuery
from posthog.queries.retention import Retention


class ClickhouseRetention(Retention):
    event_query = ClickhouseRetentionEventsQuery
    actors_query = ClickhouseRetentionActors
    actors_by_period_query = ClickhouseRetentionActorsByPeriod
