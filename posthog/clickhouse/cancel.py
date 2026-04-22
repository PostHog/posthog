from prometheus_client import Counter

from posthog import settings
from posthog.api.services.query import logger
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import default_client
from posthog.settings import CLICKHOUSE_CLUSTER

QUERY_CANCELLATION_COUNTER = Counter(
    "posthog_clickhouse_query_cancellation_total",
    "ClickHouse query cancellation attempts, per outcome.",
    labelnames=["outcome"],
)


def cancel_query_on_cluster(team_id: int, client_query_id: str) -> None:
    initiator_host = None

    QUERY_CANCELLATION_COUNTER.labels(outcome="requested").inc()
    try:
        result = sync_execute(
            """
            SELECT FQDN(), query_id
            FROM distributed_system_processes
            WHERE query_id LIKE %(client_query_id)s
            SETTINGS max_execution_time = 2
            """,
            {"client_query_id": f"{team_id}_{client_query_id}%"},
        )
        initiator_host, query_id = result[0] if (result and len(result[0]) == 2) else (None, None)
    except Exception as e:
        logger.info("Failed to find initiator host for query %s: %s", client_query_id, e)
        QUERY_CANCELLATION_COUNTER.labels(outcome="no_initiator_host").inc()

    if initiator_host:
        logger.debug("Found initiator host %s for query %s, cancelling query on host", initiator_host, client_query_id)
        with default_client(host=initiator_host) as client:
            result = sync_execute(
                "KILL QUERY WHERE query_id=%(query_id)s SETTINGS max_execution_time = 5",
                {"query_id": query_id},
                sync_client=client,
            )
        logger.info("Cancelled query %s for team %s, result: %s", client_query_id, team_id, result)
        QUERY_CANCELLATION_COUNTER.labels(outcome="ok").inc()
    elif settings.CLICKHOUSE_FALLBACK_CANCEL_QUERY_ON_CLUSTER:
        logger.debug("No initiator host found for query %s, cancelling query on cluster", client_query_id)
        # nosemgrep: clickhouse-fstring-param-audit - CLICKHOUSE_CLUSTER from settings constant
        result = sync_execute(
            f"KILL QUERY ON CLUSTER '{CLICKHOUSE_CLUSTER}' WHERE query_id LIKE %(client_query_id)s SETTINGS max_execution_time = 10, skip_unavailable_shards=1",
            {"client_query_id": f"{team_id}_{client_query_id}%"},
        )
        logger.info("Cancelled query %s for team %s, result: %s", client_query_id, team_id, result)
        QUERY_CANCELLATION_COUNTER.labels(outcome="on_cluster").inc()
