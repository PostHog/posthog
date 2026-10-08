from statshog.defaults.django import statsd

from posthog import settings
from posthog.api.services.query import logger
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import default_client
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

# The pooled clients run with an effectively unbounded send/receive timeout, so a kill issued through them
# would hold the caller's thread for as long as a stalled node stays silent. A kill is cleanup and its
# statements carry their own max_execution_time, so its sockets get a short bound instead.
_SEND_RECEIVE_TIMEOUT_SECONDS = 15


def cancel_query_on_cluster(team_id: int, client_query_id: str) -> None:
    initiator_host = None

    statsd.incr("clickhouse.query.cancellation.requested", tags={"team_id": team_id})
    try:
        with default_client(database=CLICKHOUSE_DATABASE, send_receive_timeout=_SEND_RECEIVE_TIMEOUT_SECONDS) as client:
            result = sync_execute(
                """
                SELECT FQDN(), query_id
                FROM distributed_system_processes
                WHERE query_id LIKE %(client_query_id)s
                SETTINGS max_execution_time = 2
                """,
                {"client_query_id": f"{team_id}_{client_query_id}%"},
                sync_client=client,
            )
        initiator_host, query_id = result[0] if (result and len(result[0]) == 2) else (None, None)
    except Exception as e:
        logger.info("Failed to find initiator host for query %s: %s", client_query_id, e)
        statsd.incr("clickhouse.query.cancellation.no_initiator_host", tags={"team_id": team_id})

    if initiator_host:
        logger.debug("Found initiator host %s for query %s, cancelling query on host", initiator_host, client_query_id)
        with default_client(host=initiator_host, send_receive_timeout=_SEND_RECEIVE_TIMEOUT_SECONDS) as client:
            result = sync_execute(
                "KILL QUERY WHERE query_id=%(query_id)s SETTINGS max_execution_time = 5",
                {"query_id": query_id},
                sync_client=client,
            )
        logger.info("Cancelled query %s for team %s, result: %s", client_query_id, team_id, result)
        statsd.incr("clickhouse.query.cancellation.ok", tags={"team_id": team_id})
    elif settings.CLICKHOUSE_FALLBACK_CANCEL_QUERY_ON_CLUSTER:
        logger.debug("No initiator host found for query %s, cancelling query on cluster", client_query_id)
        with default_client(database=CLICKHOUSE_DATABASE, send_receive_timeout=_SEND_RECEIVE_TIMEOUT_SECONDS) as client:
            # nosemgrep: clickhouse-fstring-param-audit - CLICKHOUSE_CLUSTER from settings constant
            result = sync_execute(
                f"KILL QUERY ON CLUSTER '{CLICKHOUSE_CLUSTER}' WHERE query_id LIKE %(client_query_id)s SETTINGS max_execution_time = 10, skip_unavailable_shards=1",
                {"client_query_id": f"{team_id}_{client_query_id}%"},
                sync_client=client,
            )
        logger.info("Cancelled query %s for team %s, result: %s", client_query_id, team_id, result)
        statsd.incr("clickhouse.query.cancellation.on_cluster", tags={"team_id": team_id})
