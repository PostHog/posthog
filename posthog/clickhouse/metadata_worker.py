"""One-shot metadata IO worker. Keep imports independent of Django for fast, killable probes."""

import sys
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from clickhouse_driver import Client

_MAX_CONCURRENT_HOST_KILLS = 8
# A physical query ID is the prefix plus the 8-character generate_short_id() suffix from validated_client_query_id().
PHYSICAL_QUERY_ID_PREDICATE = (
    "startsWith(query_id, %(client_query_id)s) AND length(query_id) = length(%(client_query_id)s) + 8"
)


def physical_query_id_prefix(team_id: int, client_query_id: str) -> str:
    return f"{team_id}_{client_query_id}_"


def run_metadata_job(job: dict[str, Any]) -> Any:
    def execute(
        sql: str,
        params: dict[str, Any],
        host: str | None = None,
        *,
        typed: bool = False,
        query_settings: dict[str, Any] | None = None,
    ) -> Any:
        kwargs = {**job["connection"]}
        if host is not None:
            kwargs["host"] = host
        settings = {**(query_settings or {}), "log_comment": job["log_comment"]}
        if kwargs.pop("transport", None) == "http":
            import clickhouse_connect  # noqa: PLC0415 - only HTTP jobs pay for this import

            http_client = clickhouse_connect.get_client(**kwargs)
            try:
                result = http_client.query(sql, parameters=params, settings=settings)
            finally:
                http_client.close()
            if typed:
                return result.result_set, [
                    (name, kind.name) for name, kind in zip(result.column_names, result.column_types)
                ]
            return result.result_set
        with Client(**kwargs) as client:
            return client.execute(sql, params, with_column_types=typed, settings=settings)

    operation = job["operation"]
    if operation == "poll":
        return execute(job["sql"], {"cluster": job["cluster"]}, query_settings={"max_execution_time": 2})
    if operation not in ("native_cancel", "legacy_cancel"):
        raise ValueError("Unsupported metadata operation")

    params = {"cluster": job["cluster"], "client_query_id": job["prefix"]}
    predicate = PHYSICAL_QUERY_ID_PREDICATE
    if operation == "native_cancel":
        # nosemgrep: clickhouse-fstring-param-audit - predicate is a constant SQL expression above
        matches = execute(
            f"SELECT FQDN(), query_id FROM clusterAllReplicas(%(cluster)s, system.processes) WHERE {predicate} SETTINGS max_execution_time=2, skip_unavailable_shards=1",
            params,
        )
        if not matches:
            return False

        query_ids_by_host: dict[str, list[str]] = {}
        for host, query_id in matches:
            query_ids_by_host.setdefault(host, []).append(query_id)

        def kill(host: str, query_ids: list[str]) -> bool:
            rows, columns = execute(
                "KILL QUERY WHERE query_id IN %(query_ids)s SYNC SETTINGS max_execution_time=5",
                {"query_ids": tuple(query_ids)},
                host,
                typed=True,
            )
            names = [name for name, _ in columns]
            if rows and ("query_id" not in names or "kill_status" not in names):
                return False
            return all(row[names.index("kill_status")] == "finished" for row in rows)

        # One connection per host, run in parallel, so stalled hosts cannot use up the shared deadline before a healthy host.
        workers = min(len(query_ids_by_host), _MAX_CONCURRENT_HOST_KILLS)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(kill, host, query_ids) for host, query_ids in query_ids_by_host.items()]
        errors = [error for future in futures if (error := future.exception()) is not None]
        if errors:
            raise errors[0]
        if not all(future.result() for future in futures):
            raise RuntimeError("Native query kill was not confirmed")
        return True

    discovery_error = None
    try:
        # nosemgrep: clickhouse-fstring-param-audit - predicate is a constant SQL expression above
        matches = execute(
            f"SELECT FQDN(), query_id FROM distributed_system_processes WHERE {predicate} SETTINGS max_execution_time=2",
            params,
        )
    except Exception as error:
        discovery_error = error
        matches = []
    if matches:
        host, query_id = matches[0]
        execute("KILL QUERY WHERE query_id=%(query_id)s SETTINGS max_execution_time=5", {"query_id": query_id}, host)
        return True
    if job["fallback"]:
        # nosemgrep: clickhouse-fstring-param-audit - predicate is constant; cluster is a bound identifier
        execute(
            f"KILL QUERY ON CLUSTER %(cluster)s WHERE {predicate} SETTINGS max_execution_time=10, skip_unavailable_shards=1",
            params,
        )
        return False
    if discovery_error is not None:
        raise discovery_error
    return False


if __name__ == "__main__":
    # clickhouse_connect probes these optional dataframe libraries on import, which adds up to seconds to a 3-second poll.
    for optional_module in ("numpy", "pandas", "pyarrow", "polars"):
        sys.modules.setdefault(optional_module, None)  # type: ignore[arg-type]
    try:
        result = run_metadata_job(json.load(sys.stdin))
        json.dump({"result": result}, sys.stdout)
    except Exception as error:
        # Driver messages can include connection details, so only the error type and ClickHouse code go back.
        code = getattr(error, "code", None)
        json.dump({"error": type(error).__name__, "code": code if isinstance(code, int) else None}, sys.stdout)
        sys.exit(1)
