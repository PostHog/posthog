from statshog.defaults.django import statsd

from posthog.api.services.query import logger
from posthog.clickhouse.client import sync_execute
from posthog.settings import CLICKHOUSE_CLUSTER


def cancel_query_on_cluster(team_id: int, client_query_id: str) -> None:
    result = sync_execute(
        f"KILL QUERY ON CLUSTER '{CLICKHOUSE_CLUSTER}' WHERE query_id LIKE %(client_query_id)s",
        {"client_query_id": f"{team_id}_{client_query_id}%"},
    )
    logger.info("Cancelled query %s for team %s, result: %s", client_query_id, team_id, result)
    statsd.incr("clickhouse.query.cancellation_requested", tags={"team_id": team_id})
