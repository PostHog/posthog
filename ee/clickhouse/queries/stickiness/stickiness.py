from ee.clickhouse.queries.stickiness.stickiness_actors import (
    ClickhouseStickinessActors,
)
from ee.clickhouse.queries.stickiness.stickiness_event_query import (
    ClickhouseStickinessEventsQuery,
)
from posthog.queries.stickiness.stickiness import Stickiness


class ClickhouseStickiness(Stickiness):
    event_query_class = ClickhouseStickinessEventsQuery
    actor_query_class = ClickhouseStickinessActors
