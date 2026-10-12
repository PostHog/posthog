from concurrent.futures import Future
from functools import partial
from time import monotonic

from django.conf import settings

from statshog.defaults.django import statsd

from posthog.api.services.query import logger
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import default_client
from posthog.clickhouse.native_metadata import submit_native_metadata
from posthog.clickhouse.query_tagging import tags_context
from posthog.clickhouse.workload import Workload
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

# The pooled clients run with an effectively unbounded send/receive timeout, so a kill issued through them
# would hold the caller's thread for as long as a stalled node stays silent. A kill is cleanup and its
# statements carry their own max_execution_time, so its sockets get a short bound instead.
_SEND_RECEIVE_TIMEOUT_SECONDS = 15


# validated_client_query_id appends one underscore and exactly eight random characters.
def _cancel_native_query(team_id: int, client_query_id: str) -> bool:
    with default_client(
        workload=Workload.NATIVE_EVENTS,
        team_id=team_id,
        database=CLICKHOUSE_DATABASE,
        connect_timeout=1,
        send_receive_timeout=_SEND_RECEIVE_TIMEOUT_SECONDS,
    ) as client:
        # nosemgrep: clickhouse-fstring-param-audit - CLICKHOUSE_CLUSTER is a settings constant
        rows, columns = sync_execute(
            f"KILL QUERY ON CLUSTER '{CLICKHOUSE_CLUSTER}' WHERE startsWith(query_id, %(client_query_id)s) AND length(query_id) = length(%(client_query_id)s) + 8 SETTINGS max_execution_time = 10, skip_unavailable_shards=1",
            {"client_query_id": f"{team_id}_{client_query_id}_"},
            sync_client=client,
            with_column_types=True,
        )
    statsd.incr("clickhouse.query.cancellation.native", tags={"team_id": team_id})
    names = [name for name, _ in columns]
    if "query_id" not in names or "kill_status" not in names:
        return False
    query_index, status_index = names.index("query_id"), names.index("kill_status")
    prefix = f"{team_id}_{client_query_id}_"
    return any(
        row[status_index] in ("waiting", "finished")
        and str(row[query_index]).startswith(prefix)
        and len(str(row[query_index])) == len(prefix) + 8
        for row in rows
    )


def _log_native_cancellation(team_id: int, client_query_id: str, future: Future[bool]) -> None:
    if not future.cancelled() and (error := future.exception()) is not None:
        logger.warning("Failed to cancel native query %s: %s", client_query_id, error)
        statsd.incr("clickhouse.query.cancellation.native_failed", tags={"team_id": team_id})


def cancel_query_on_cluster(team_id: int, client_query_id: str) -> None:
    statsd.incr("clickhouse.query.cancellation.requested", tags={"team_id": team_id})
    # Cleanup queries must not appear among the queries they discover or cancel.
    with tags_context(team_id=None, client_query_id=None):
        native = None
        native_deadline = None
        if settings.CLICKHOUSE_NATIVE_EVENTS_HOST:
            native_deadline = monotonic() + 20
            native = submit_native_metadata(partial(_cancel_native_query, team_id, client_query_id))
            if native is not None:
                native.add_done_callback(partial(_log_native_cancellation, team_id, client_query_id))

        legacy_error = None
        try:
            legacy_found = _cancel_legacy_query(team_id, client_query_id)
        except Exception as error:
            if not settings.CLICKHOUSE_NATIVE_EVENTS_HOST:
                raise
            legacy_error = error
            legacy_found = False
            logger.warning("Failed to cancel legacy query %s: %s", client_query_id, error)
        if legacy_found or not settings.CLICKHOUSE_NATIVE_EVENTS_HOST:
            return
        if native is None:
            raise RuntimeError("Native query cancellation is busy; retry cancellation")
        # DNS and connection retries can outlive individual socket timeouts.
        assert native_deadline is not None
        confirmed = native.result(timeout=max(0.0, native_deadline - monotonic()))
        if legacy_error is not None and not confirmed:
            raise legacy_error


def _cancel_legacy_query(team_id: int, client_query_id: str) -> bool:
    initiator_host = None
    discovery_error = None
    try:
        with default_client(database=CLICKHOUSE_DATABASE, send_receive_timeout=_SEND_RECEIVE_TIMEOUT_SECONDS) as client:
            result = sync_execute(
                """
                SELECT FQDN(), query_id
                FROM distributed_system_processes
                WHERE startsWith(query_id, %(client_query_id)s) AND length(query_id) = length(%(client_query_id)s) + 8
                SETTINGS max_execution_time = 2
                """,
                {"client_query_id": f"{team_id}_{client_query_id}_"},
                sync_client=client,
            )
        initiator_host, query_id = result[0] if (result and len(result[0]) == 2) else (None, None)
    except Exception as e:
        discovery_error = e
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
                f"KILL QUERY ON CLUSTER '{CLICKHOUSE_CLUSTER}' WHERE startsWith(query_id, %(client_query_id)s) AND length(query_id) = length(%(client_query_id)s) + 8 SETTINGS max_execution_time = 10, skip_unavailable_shards=1",
                {"client_query_id": f"{team_id}_{client_query_id}_"},
                sync_client=client,
            )
        logger.info("Cancelled query %s for team %s, result: %s", client_query_id, team_id, result)
        statsd.incr("clickhouse.query.cancellation.on_cluster", tags={"team_id": team_id})
    # A cluster kill can succeed with no matching rows. Preserve failed discovery until
    # the coordinator can confirm native cleanup instead of deleting an unknown query's status.
    if settings.CLICKHOUSE_NATIVE_EVENTS_HOST and discovery_error is not None:
        raise discovery_error
    return initiator_host is not None
