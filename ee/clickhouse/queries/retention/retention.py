from ee.clickhouse.queries.retention.retention_actors import (
    ClickhouseRetentionActorsByPeriod,
)
from ee.clickhouse.queries.retention.retention_event_query import (
    ClickhouseRetentionEventsQuery,
)
from posthog.queries.retention.retention import Retention


class ClickhouseRetention(Retention):
    event_query = ClickhouseRetentionEventsQuery
    actors_by_period_query = ClickhouseRetentionActorsByPeriod
