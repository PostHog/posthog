import sys
import json
import subprocess
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore, Lock
from time import monotonic
from typing import Any

from django.conf import settings

from statshog.defaults.django import statsd

from posthog.clickhouse.client.connection import ClickHouseUser, Workload, default_client_kwargs
from posthog.clickhouse.query_tagging import get_query_tags

POLL_DEADLINE_SECONDS = 3.0
CANCEL_DEADLINE_SECONDS = 20.0

_pools: dict[tuple[bool, bool], tuple[ThreadPoolExecutor, BoundedSemaphore]] = {}
_pool_lock = Lock()


def metadata_connection(
    *, native_host: str | None = None, team_id: int | None = None, polling: bool = False
) -> dict[str, Any]:
    # Resolve settings before scheduling; the killable child owns all DNS and ClickHouse network IO.
    kwargs = default_client_kwargs(
        host=native_host,
        database="system" if polling else settings.CLICKHOUSE_DATABASE,
        workload=Workload.DEFAULT if native_host else Workload.ONLINE if polling else None,
        ch_user=ClickHouseUser.OPS if polling else ClickHouseUser.DEFAULT,
        team_id=team_id,
        connect_timeout=1,
        send_receive_timeout=2 if polling else 15,
    )

    if native_host:
        kwargs["verify"] = settings.CLICKHOUSE_VERIFY
    elif polling and settings.CLICKHOUSE_USE_HTTP:
        kwargs.pop("ca_certs", None)
        kwargs.update(transport="http", ca_cert=settings.CLICKHOUSE_CA, verify=settings.QUERYSERVICE_VERIFY)
    return kwargs


def submit_native_metadata(
    job: dict[str, Any],
    *,
    native_host: str,
    team_id: int | None = None,
    deadline: float | None = None,
) -> Future[Any] | None:
    polling = _is_poll(job)
    job = {
        **job,
        "cluster": settings.CLICKHOUSE_EVENTS_CLUSTER,
        "connection": metadata_connection(native_host=native_host, team_id=team_id, polling=polling),
    }
    return _submit_metadata(job, native=True, polling=polling, deadline=deadline)


def submit_legacy_metadata(job: dict[str, Any], *, deadline: float | None = None) -> Future[Any] | None:
    polling = _is_poll(job)
    job = {**job, "cluster": settings.CLICKHOUSE_CLUSTER, "connection": metadata_connection(polling=polling)}
    return _submit_metadata(job, native=False, polling=polling, deadline=deadline)


def _is_poll(job: dict[str, Any]) -> bool:
    return job.get("operation") == "poll"


def _submit_metadata(job: dict[str, Any], *, native: bool, polling: bool, deadline: float | None) -> Future[Any] | None:
    if deadline is None:
        deadline = monotonic() + (POLL_DEADLINE_SECONDS if polling else CANCEL_DEADLINE_SECONDS)
    key = (native, polling)
    with _pool_lock:
        if key not in _pools:
            capacity = 1 if polling else 4
            _pools[key] = (
                ThreadPoolExecutor(max_workers=capacity, thread_name_prefix=f"metadata_{native}_{polling}"),
                BoundedSemaphore(capacity),
            )
        executor, slots = _pools[key]
    if not slots.acquire(blocking=False):
        statsd.incr(
            "clickhouse.metadata.busy",
            tags={"cluster": "native" if native else "legacy", "operation": "poll" if polling else "cancel"},
        )
        return None
    try:
        payload = json.dumps({**job, "log_comment": get_query_tags().to_json()})
        future = executor.submit(_run_metadata_process, payload, deadline)
    except BaseException:
        slots.release()
        raise
    future.add_done_callback(lambda _: slots.release())
    return future


def _failure_summary(output: str) -> str:
    try:
        failure = json.loads(output)
    except ValueError:
        return "no details"
    summary = str(failure.get("error", "no details"))
    return f"{summary} (code {failure['code']})" if failure.get("code") is not None else summary


def _run_metadata_process(payload: str, deadline: float) -> Any:
    # A Future timeout cannot stop DNS or a stuck driver. Only the child performs network IO;
    # kill and reap it before releasing capacity, including when the supervising thread fails.
    with subprocess.Popen(
        [sys.executable, "-P", str(Path(__file__).with_name("metadata_worker.py"))],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    ) as process:
        try:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("ClickHouse metadata deadline exceeded")
            output, _ = process.communicate(payload, timeout=remaining)
            if process.returncode:
                raise RuntimeError(f"ClickHouse metadata operation failed: {_failure_summary(output)}")
            return json.loads(output)["result"]
        except subprocess.TimeoutExpired:
            raise TimeoutError("ClickHouse metadata deadline exceeded") from None
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
