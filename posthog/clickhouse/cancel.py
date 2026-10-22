from concurrent.futures import FIRST_COMPLETED, Future, wait
from functools import partial
from time import monotonic

from django.conf import settings

from statshog.defaults.django import statsd

from posthog.api.services.query import logger
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import default_client
from posthog.clickhouse.metadata_worker import PHYSICAL_QUERY_ID_PREDICATE, physical_query_id_prefix
from posthog.clickhouse.native_metadata import CANCEL_DEADLINE_SECONDS, submit_legacy_metadata, submit_native_metadata
from posthog.clickhouse.query_tagging import tags_context
from posthog.models.event.new_events_schema import (
    get_new_events_cluster_host_or_none,
    native_events_cluster_ineligibility,
)
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

# The pooled clients run with an effectively unbounded send/receive timeout, so a kill issued through them
# would hold the caller's thread for as long as a stalled node stays silent. A kill is cleanup and its
# statements carry their own max_execution_time, so its sockets get a short bound instead.
_SEND_RECEIVE_TIMEOUT_SECONDS = 15


def _log_native_cancellation(team_id: int, client_query_id: str, future: Future[bool]) -> None:
    if not future.cancelled() and (error := future.exception()) is not None:
        logger.warning("Failed to cancel native query %s: %s", client_query_id, error)
        statsd.incr("clickhouse.query.cancellation.native_failed", tags={"team_id": team_id})
    elif not future.cancelled() and future.result():
        statsd.incr("clickhouse.query.cancellation.native", tags={"team_id": team_id})


def cancel_query_on_cluster(team_id: int, client_query_id: str) -> None:
    statsd.incr("clickhouse.query.cancellation.requested", tags={"team_id": team_id})
    # Cleanup queries must not appear among the queries they discover or cancel.
    with tags_context(team_id=None, client_query_id=None):
        native_host = get_new_events_cluster_host_or_none()
        try:
            # Only projects enabled for the native cluster can have queries there.
            native_enabled = bool(native_host) and native_events_cluster_ineligibility(team_id) is None
        except Exception:
            logger.exception("Failed to resolve native query cancellation eligibility")
            native_enabled = False
        if not native_host or not native_enabled:
            _cancel_legacy_query(team_id, client_query_id)
            return

        deadline = monotonic() + CANCEL_DEADLINE_SECONDS
        common = {
            "prefix": physical_query_id_prefix(team_id, client_query_id),
            "fallback": settings.CLICKHOUSE_FALLBACK_CANCEL_QUERY_ON_CLUSTER,
        }
        try:
            legacy = submit_legacy_metadata({**common, "operation": "legacy_cancel"}, deadline=deadline)
        except Exception as exc:
            legacy = Future()
            legacy.set_exception(exc)
        try:
            native = submit_native_metadata(
                {**common, "operation": "native_cancel"}, native_host=native_host, team_id=team_id, deadline=deadline
            )
        except Exception as exc:
            native = Future()
            native.set_exception(exc)
        if native is not None:
            native.add_done_callback(partial(_log_native_cancellation, team_id, client_query_id))
        pending = {future for future in (legacy, native) if future is not None}
        error: Exception | None = None
        while pending:
            finished, pending = wait(pending, timeout=max(0.0, deadline - monotonic()), return_when=FIRST_COMPLETED)
            if not finished:
                raise TimeoutError("Query cancellation exceeded its deadline")
            for future in finished:
                try:
                    if future.result():
                        if future is legacy:
                            statsd.incr("clickhouse.query.cancellation.ok", tags={"team_id": team_id})
                        return
                except Exception as exc:
                    error = exc
        if error is not None:
            raise error
        if legacy is None or native is None:
            busy = "Legacy" if legacy is None else "Native"
            raise RuntimeError(f"{busy} query cancellation is busy; retry cancellation")


def _cancel_legacy_query(team_id: int, client_query_id: str) -> None:
    initiator_host = None
    try:
        with default_client(database=CLICKHOUSE_DATABASE, send_receive_timeout=_SEND_RECEIVE_TIMEOUT_SECONDS) as client:
            # nosemgrep: clickhouse-fstring-param-audit - the predicate is a constant SQL expression
            result = sync_execute(
                f"""
                SELECT FQDN(), query_id
                FROM distributed_system_processes
                WHERE {PHYSICAL_QUERY_ID_PREDICATE}
                SETTINGS max_execution_time = 2
                """,
                {"client_query_id": physical_query_id_prefix(team_id, client_query_id)},
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
            # nosemgrep: clickhouse-fstring-param-audit - CLICKHOUSE_CLUSTER and the predicate are constants
            result = sync_execute(
                f"KILL QUERY ON CLUSTER '{CLICKHOUSE_CLUSTER}' WHERE {PHYSICAL_QUERY_ID_PREDICATE} SETTINGS max_execution_time = 10, skip_unavailable_shards=1",
                {"client_query_id": physical_query_id_prefix(team_id, client_query_id)},
                sync_client=client,
            )
        logger.info("Cancelled query %s for team %s, result: %s", client_query_id, team_id, result)
        statsd.incr("clickhouse.query.cancellation.on_cluster", tags={"team_id": team_id})
