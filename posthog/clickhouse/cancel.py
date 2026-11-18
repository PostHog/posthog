from statshog.defaults.django import statsd

from posthog import settings
from posthog.api.services.query import logger
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import default_client
from posthog.settings import CLICKHOUSE_DATABASE

# The pooled clients run with an effectively unbounded send/receive timeout, so a kill issued through them
# would hold the caller's thread for as long as a stalled node stays silent. A kill is cleanup and its
# statements carry their own max_execution_time, so its sockets get a short bound instead.
_SEND_RECEIVE_TIMEOUT_SECONDS = 15


def cancel_query_on_cluster(team_id: int, client_query_id: str) -> None:
    initiator_host = None
    # Cancel requests do not carry the query's schema override, so either cluster can own the query.
    clusters = {settings.CLICKHOUSE_CLUSTER: settings.CLICKHOUSE_HOST}
    events_host = settings.CLICKHOUSE_EVENTS_ONLINE_HOST or settings.CLICKHOUSE_EVENTS_OFFLINE_HOST
    if events_host:
        clusters[settings.CLICKHOUSE_EVENTS_CLUSTER] = events_host

    statsd.incr("clickhouse.query.cancellation.requested", tags={"team_id": team_id})
    for cluster, lookup_host in clusters.items():
        try:
            with default_client(
                host=lookup_host, database=CLICKHOUSE_DATABASE, send_receive_timeout=_SEND_RECEIVE_TIMEOUT_SECONDS
            ) as client:
                result = sync_execute(
                    """
                    SELECT FQDN(), query_id
                    FROM clusterAllReplicas(%(cluster)s, system.processes)
                    WHERE startsWith(query_id, %(client_query_id)s)
                    SETTINGS max_execution_time = 2, skip_unavailable_shards = 1
                    """,
                    {"cluster": cluster, "client_query_id": f"{team_id}_{client_query_id}"},
                    sync_client=client,
                )
            initiator_host, query_id = result[0] if (result and len(result[0]) == 2) else (None, None)
        except Exception as e:
            logger.info("Failed to find initiator host for query %s: %s", client_query_id, e)
            statsd.incr("clickhouse.query.cancellation.no_initiator_host", tags={"team_id": team_id})
        if initiator_host:
            break

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
        cancellation_error: Exception | None = None
        for cluster, lookup_host in clusters.items():
            try:
                with default_client(
                    host=lookup_host, database=CLICKHOUSE_DATABASE, send_receive_timeout=_SEND_RECEIVE_TIMEOUT_SECONDS
                ) as client:
                    # nosemgrep: clickhouse-fstring-param-audit - cluster is a cluster name from settings
                    result = sync_execute(
                        f"KILL QUERY ON CLUSTER '{cluster}' WHERE startsWith(query_id, %(client_query_id)s) SETTINGS max_execution_time = 10, skip_unavailable_shards=1",
                        {"client_query_id": f"{team_id}_{client_query_id}"},
                        sync_client=client,
                    )
            except Exception as exc:
                cancellation_error = exc
                continue
            logger.info("Cancelled query %s for team %s, result: %s", client_query_id, team_id, result)
            statsd.incr("clickhouse.query.cancellation.on_cluster", tags={"team_id": team_id})
        if cancellation_error is not None:
            raise cancellation_error
