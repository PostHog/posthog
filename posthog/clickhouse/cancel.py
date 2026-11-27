from collections import defaultdict

from statshog.defaults.django import statsd

from posthog import settings
from posthog.api.services.query import logger
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import default_client
from posthog.clickhouse.query_tagging import tags_context
from posthog.settings import CLICKHOUSE_DATABASE
from posthog.utils import UUID_REGEX

# The pooled clients run with an effectively unbounded send/receive timeout, so a kill issued through them
# would hold the caller's thread for as long as a stalled node stays silent. A kill is cleanup and its
# statements carry their own max_execution_time, so its sockets get a short bound instead.
_SEND_RECEIVE_TIMEOUT_SECONDS = 15


def _lookup_hosts() -> dict[str, str]:
    # Cancel requests do not carry the query's schema override, so either cluster can own the query.
    clusters = {settings.CLICKHOUSE_CLUSTER: settings.CLICKHOUSE_HOST}
    events_host = settings.CLICKHOUSE_EVENTS_ONLINE_HOST or settings.CLICKHOUSE_EVENTS_OFFLINE_HOST
    if events_host:
        clusters[settings.CLICKHOUSE_EVENTS_CLUSTER] = events_host
    return clusters


def _kill_queries_on_host(host: str, query_ids: list[str]) -> list[tuple[object, ...]]:
    with default_client(host=host, send_receive_timeout=_SEND_RECEIVE_TIMEOUT_SECONDS) as client:
        return sync_execute(
            "KILL QUERY WHERE query_id IN %(query_ids)s ASYNC SETTINGS max_execution_time = 5",
            {"query_ids": query_ids},
            sync_client=client,
        )


def cancel_query_on_cluster(team_id: int, client_query_id: str) -> None:
    initiator_host = None
    clusters = _lookup_hosts()

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
            if result and len(result[0]) == 2:
                initiator_host, query_id = result[0]
        except Exception as e:
            logger.info("Failed to find initiator host for query %s: %s", client_query_id, e)
            statsd.incr("clickhouse.query.cancellation.no_initiator_host", tags={"team_id": team_id})
        if initiator_host:
            break

    if initiator_host:
        logger.debug("Found initiator host %s for query %s, cancelling query on host", initiator_host, client_query_id)
        result = _kill_queries_on_host(initiator_host, [query_id])
        logger.info("Cancelled query %s for team %s, result: %s", client_query_id, team_id, result)
        statsd.incr("clickhouse.query.cancellation.ok", tags={"team_id": team_id})
    elif settings.CLICKHOUSE_FALLBACK_CANCEL_QUERY_ON_CLUSTER:
        logger.debug("No initiator host found for query %s, cancelling query on cluster", client_query_id)
        _cancel_on_clusters(
            clusters,
            team_id,
            "KILL QUERY ON CLUSTER %(cluster)s WHERE startsWith(query_id, %(client_query_id)s) "
            "SETTINGS max_execution_time = 10, skip_unavailable_shards=1",
            {"client_query_id": f"{team_id}_{client_query_id}"},
        )


def _cancel_on_clusters(clusters: dict[str, str], team_id: int, query: str, params: dict[str, str]) -> None:
    cancellation_error: Exception | None = None
    for cluster, lookup_host in clusters.items():
        try:
            with default_client(
                host=lookup_host, database=CLICKHOUSE_DATABASE, send_receive_timeout=_SEND_RECEIVE_TIMEOUT_SECONDS
            ) as client:
                result = sync_execute(query, {"cluster": cluster, **params}, sync_client=client)
        except Exception as exc:
            cancellation_error = exc
            continue
        logger.info("Issued cancellation on cluster %s for team %s, result: %s", cluster, team_id, result)
        statsd.incr("clickhouse.query.cancellation.on_cluster", tags={"team_id": team_id})
    if cancellation_error is not None:
        raise cancellation_error


# A failed series can invoke cleanup from inside its own query tags. The lookup and kills must not match themselves.
@tags_context(client_query_id=None)
def cancel_queries_started_for(team_id: int, client_query_id: str, *, fallback_on_cluster: bool = False) -> None:
    """Cancels the query of a team that runs under `client_query_id`, and the queries started for it.

    A query started on behalf of another one puts that query's id after its own, which is a UUID, as in
    `{team_id}_{own_id}_{client_query_id}_{random}`. `cancel_query_on_cluster` matches a query id by its
    start, so it does not find such a query. The match is on these two whole shapes, because a caller
    chooses its client query id, and one that merely contains this id belongs to another query.
    """
    statsd.incr("clickhouse.query.cancellation.requested", tags={"team_id": team_id})
    match_params = {
        "start": f"^{team_id}_({UUID_REGEX}_)?",
        "client_query_id": client_query_id,
        "end": "_[A-Za-z0-9]{8}$",
    }
    clusters = _lookup_hosts()
    by_host: dict[str, set[str]] = defaultdict(set)
    for cluster, lookup_host in clusters.items():
        try:
            with default_client(
                host=lookup_host, database=CLICKHOUSE_DATABASE, send_receive_timeout=_SEND_RECEIVE_TIMEOUT_SECONDS
            ) as client:
                running = sync_execute(
                    """
                    SELECT FQDN(), query_id
                    FROM clusterAllReplicas(%(cluster)s, system.processes)
                    WHERE match(query_id, concat(%(start)s, regexpQuoteMeta(%(client_query_id)s), %(end)s))
                    SETTINGS max_execution_time = 2, skip_unavailable_shards = 1
                    """,
                    {"cluster": cluster, **match_params},
                    sync_client=client,
                )
        except Exception as e:
            logger.info("Failed to look up queries started for %s: %s", client_query_id, e)
            statsd.incr("clickhouse.query.cancellation.no_initiator_host", tags={"team_id": team_id})
            continue
        for host, query_id in running:
            by_host[host].add(query_id)

    cancelled = 0
    for host, query_ids in by_host.items():
        try:
            _kill_queries_on_host(host, sorted(query_ids))
        except Exception as e:
            logger.warning("Failed to cancel queries on %s for %s: %s", host, client_query_id, e)
            statsd.incr("clickhouse.query.cancellation.kill_failed", len(query_ids), tags={"team_id": team_id})
            continue
        cancelled += len(query_ids)
        statsd.incr("clickhouse.query.cancellation.ok", len(query_ids), tags={"team_id": team_id})
    logger.info("Issued cancellation for %s queries started for %s, team %s", cancelled, client_query_id, team_id)
    if not by_host and fallback_on_cluster:
        _cancel_on_clusters(
            clusters,
            team_id,
            "KILL QUERY ON CLUSTER %(cluster)s "
            "WHERE match(query_id, concat(%(start)s, regexpQuoteMeta(%(client_query_id)s), %(end)s)) "
            "ASYNC SETTINGS max_execution_time = 10, skip_unavailable_shards = 1",
            match_params,
        )
