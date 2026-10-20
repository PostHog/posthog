"""One-shot metadata IO worker. Keep imports independent of Django for fast, killable probes."""

import sys
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from clickhouse_driver import Client


def run_metadata_job(job: dict[str, Any]) -> Any:
    def execute(sql: str, params: dict[str, Any], host: str | None = None, *, typed: bool = False) -> Any:
        kwargs = {**job["connection"]}
        if host is not None:
            kwargs["host"] = host
        settings = {"log_comment": job["log_comment"]}
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
        return execute(job["sql"] + ", max_execution_time=2", {"cluster": job["cluster"]})
    if operation not in ("native_cancel", "legacy_cancel"):
        raise ValueError("Unsupported metadata operation")

    params = {"cluster": job["cluster"], "client_query_id": job["prefix"]}
    predicate = "startsWith(query_id, %(client_query_id)s) AND length(query_id) = length(%(client_query_id)s) + 8"
    if operation == "native_cancel":
        # nosemgrep: clickhouse-fstring-param-audit - predicate is a constant SQL expression above
        matches = execute(
            f"SELECT FQDN(), query_id FROM clusterAllReplicas(%(cluster)s, system.processes) WHERE {predicate} SETTINGS max_execution_time=2, skip_unavailable_shards=1",
            params,
        )
        if not matches:
            return False

        def kill(match: tuple[str, str]) -> bool:
            host, query_id = match
            rows, columns = execute(
                "KILL QUERY WHERE query_id=%(query_id)s SYNC SETTINGS max_execution_time=5",
                {"query_id": query_id},
                host,
                typed=True,
            )
            names = [name for name, _ in columns]
            return (
                "query_id" in names
                and "kill_status" in names
                and any(
                    row[names.index("kill_status")] == "finished" and row[names.index("query_id")] == query_id
                    for row in rows
                )
            )

        # Kill on every host at once, so stalled hosts cannot use up the shared deadline before a healthy host.
        with ThreadPoolExecutor(max_workers=len(matches)) as executor:
            futures = [executor.submit(kill, match) for match in matches]
        errors = [error for future in futures if (error := future.exception()) is not None]
        if errors:
            raise errors[0]
        return all(future.result() for future in futures)

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
    if discovery_error is not None:
        raise discovery_error
    return False


if __name__ == "__main__":
    try:
        result = run_metadata_job(json.load(sys.stdin))
        json.dump({"result": result}, sys.stdout)
    except Exception as error:
        # Driver messages can include connection details, so only the error type and ClickHouse code go back.
        code = getattr(error, "code", None)
        json.dump({"error": type(error).__name__, "code": code if isinstance(code, int) else None}, sys.stdout)
        sys.exit(1)
