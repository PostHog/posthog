import re
import html
import json
import math
import uuid
import difflib
import dataclasses
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import time_machine
from unittest.mock import patch

from django.conf import settings

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import get_client_from_pool
from posthog.clickhouse.client.escape import substitute_params
from posthog.clickhouse.query_tagging import tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team
from posthog.storage import object_storage

SAMPLE_DAYS = 7
SAMPLE_ONE_IN = 100
LOOKUP_DAYS = 30
OVERSAMPLE = 3
SAMPLE_SETTINGS = {"max_execution_time": 120}
_LOGGED = "type = 'QueryFinish' AND is_initial_query AND lc_query__kind != '' AND team_id > 0"
MAX_EXECUTED = 200
REGRESSION_FACTOR = 1.5
ROW_CAP = 10_000
DIFFERENCES_SHOWN = 20
EXECUTION_SETTINGS = {"use_query_condition_cache": 0, "max_execution_time": 60}

_LEADING_COMMENTS = re.compile(r"^(\s*/\*.*?\*/)+", re.DOTALL)
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d+)?")
_MAX_EXECUTION_TIME = re.compile(r"max_execution_time=\d+")
_UNSAFE_IN_FILE_NAME = re.compile(r"[^A-Za-z0-9_.-]")
_CONTENT_TYPES = {".html": "text/html", ".json": "application/json"}
_TAG = re.compile(r"replay-[0-9a-f]+-\d+-[a-z0-9]+")


class Verdict(StrEnum):
    IDENTICAL_SQL = "identical_sql"
    SAME_RESULTS = "same_results"
    DIFFERENT_RESULTS = "different_results"
    HEAD_ONLY_ERROR = "head_only_error"
    UNSTABLE = "unstable"
    COULD_NOT_MODEL = "could_not_model"
    NOT_RUN = "not_run"


@frozen
class LoggedQuery:
    query_id: str
    team_id: int
    kind: str
    query_json: str
    prod_sql: str
    started_at: datetime


@frozen
class CompiledQuery:
    query_id: str
    sql: str | None = None
    error: str | None = None


Row = tuple[Any, ...]


@frozen
class RunResult:
    row_count: int | None = None
    fingerprint: int | None = None
    columns: tuple[tuple[str, str], ...] = ()
    rows: tuple[Row, ...] | None = None
    error: str | None = None


@frozen
class Outcome:
    logged: LoggedQuery
    verdict: Verdict
    base_sql: str | None = None
    head_sql: str | None = None
    error: str | None = None
    base_rows: int | None = None
    head_rows: int | None = None
    columns: tuple[tuple[str, str], ...] = ()
    base_only: tuple[Row, ...] = ()
    head_only: tuple[Row, ...] = ()
    base_tag: str | None = None
    head_tag: str | None = None


Execute = Callable[[str, int, str], RunResult]


def write_jsonl(path: Path, items: Iterable[LoggedQuery | CompiledQuery]) -> None:
    with path.open("w") as f:
        for item in items:
            f.write(json.dumps(dataclasses.asdict(item), default=str) + "\n")


def read_logged_queries(path: Path) -> list[LoggedQuery]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line]
    return [LoggedQuery(**{**row, "started_at": datetime.fromisoformat(row["started_at"])}) for row in rows]


def read_compiled_queries(path: Path) -> dict[str, CompiledQuery]:
    compiled = [CompiledQuery(**json.loads(line)) for line in path.read_text().splitlines() if line]
    return {c.query_id: c for c in compiled}


def load_logged_queries(query_ids: Sequence[str] = (), sample_size: int = 0) -> list[LoggedQuery]:
    if query_ids:
        selection = f"event_date >= today() - {LOOKUP_DAYS} AND query_id IN %(query_ids)s"
    else:
        selection = f"""event_date >= today() - {SAMPLE_DAYS} AND query_id IN (
            SELECT query_id FROM query_log_archive
            WHERE event_date >= today() - {SAMPLE_DAYS} AND {_LOGGED} AND rand() %% {SAMPLE_ONE_IN} = 0
        )"""
    rows = sync_execute(
        f"""
        SELECT query_id, team_id, lc_query__kind, lc_query, query, query_start_time, lc_client_query_id
        FROM query_log_archive
        WHERE {selection} AND {_LOGGED}
        ORDER BY rand()
        LIMIT 1 BY team_id, cityHash64(lc_query)
        LIMIT %(limit)s
        """,
        {"query_ids": list(query_ids), "limit": len(query_ids) or sample_size * OVERSAMPLE},
        settings=SAMPLE_SETTINGS,
        workload=Workload.OFFLINE,
        readonly=True,
    )
    single_statement = _single_statement_requests([row[6] for row in rows])
    logged = [
        LoggedQuery(
            query_id=query_id,
            team_id=team_id,
            kind=kind,
            query_json=query_json,
            prod_sql=prod_sql,
            started_at=started_at.replace(tzinfo=UTC),
        )
        for query_id, team_id, kind, query_json, prod_sql, started_at, client_query_id in rows
        if (team_id, client_query_id) in single_statement
    ]
    return logged[: len(query_ids) or sample_size]


def _single_statement_requests(client_query_ids: Sequence[str]) -> set[tuple[int, str]]:
    rows = sync_execute(
        f"""
        SELECT team_id, lc_client_query_id
        FROM query_log_archive
        WHERE event_date >= today() - {LOOKUP_DAYS} AND {_LOGGED} AND lc_client_query_id IN %(client_query_ids)s
        GROUP BY team_id, lc_client_query_id
        HAVING count() = 1
        """,
        {"client_query_ids": [client_query_id for client_query_id in client_query_ids if client_query_id]},
        settings=SAMPLE_SETTINGS,
        workload=Workload.OFFLINE,
        readonly=True,
    )
    return {(team_id, client_query_id) for team_id, client_query_id in rows}


class _MetadataOnlyClient:
    def __init__(self, client: Any, blocked: list[str]) -> None:
        self._client = client
        self._blocked = blocked

    def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
        if "system." not in sql:
            self._blocked.append(sql)
            raise RuntimeError("Replay compile does not run queries")
        return self._client.execute(sql, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def compile_logged_query(logged: LoggedQuery) -> CompiledQuery:
    captured: list[str] = []
    blocked: list[str] = []

    def record(
        sql: str, values: Mapping[str, Any] | None = None, **_: Any
    ) -> tuple[list[Any], list[Any]]:  # nosemgrep: tuple-return-prefer-dataclass -- stands in for sync_execute
        captured.append(substitute_params(sql, dict(values or {})))
        return [], []

    @contextmanager
    def metadata_only_pool(*args: Any, **kwargs: Any) -> Iterator[_MetadataOnlyClient]:
        with get_client_from_pool(*args, **kwargs) as client:
            yield _MetadataOnlyClient(client, blocked)

    failure: Exception | None = None
    try:
        with (
            time_machine.travel(logged.started_at, tick=False),
            patch("posthog.hogql.query.sync_execute", side_effect=record),
            patch("posthog.clickhouse.client.execute.get_client_from_pool", metadata_only_pool),
        ):
            team = Team.objects.get(pk=logged.team_id)
            get_query_runner(query=json.loads(logged.query_json), team=team).calculate()
    except Exception as e:
        failure = e

    statements = len(captured) + len(blocked)
    if statements == 1 and captured:
        return CompiledQuery(query_id=logged.query_id, sql=captured[0])
    if statements:
        return CompiledQuery(query_id=logged.query_id, error=f"Runner issued {statements} statements")
    return CompiledQuery(query_id=logged.query_id, error=repr(failure) if failure else "Runner issued no statement")


def normalize_sql(sql: str) -> str:
    without_comments = _LEADING_COMMENTS.sub("", sql)
    without_timestamps = _TIMESTAMP.sub("<ts>", " ".join(without_comments.split()))
    return _MAX_EXECUTION_TIME.sub("max_execution_time=<n>", without_timestamps)


def execute_on_clickhouse(sql: str, team_id: int, tag: str) -> RunResult:
    def run(wrapped: str) -> list[Row]:
        with tags_context(client_query_id=tag, team_id=team_id):
            return sync_execute(
                wrapped, settings=EXECUTION_SETTINGS, workload=Workload.OFFLINE, team_id=team_id, readonly=True
            )

    try:
        described = sync_execute(f"DESCRIBE ({sql})", workload=Workload.OFFLINE, team_id=team_id, readonly=True)
        columns = tuple((row[0], row[1]) for row in described)
        rows = run(f"SELECT * FROM ({sql}) LIMIT {ROW_CAP + 1}")
        if len(rows) <= ROW_CAP:
            return RunResult(row_count=len(rows), columns=columns, rows=tuple(tuple(row) for row in rows))
        row_count, fingerprint = run(f"SELECT count(), sum(cityHash64(toString(tuple(*)))) FROM ({sql})")[0]
    except Exception as e:
        return RunResult(error=repr(e))
    return RunResult(row_count=row_count, fingerprint=fingerprint, columns=columns)


def results_match(a: RunResult, b: RunResult) -> bool:
    if a.error or b.error or a.columns != b.columns:
        return False
    if a.rows is not None and b.rows is not None:
        return not any(row_differences(a.rows, b.rows))
    return a.rows is None and b.rows is None and (a.row_count, a.fingerprint) == (b.row_count, b.fingerprint)


def row_differences(base: Sequence[Row], head: Sequence[Row]) -> tuple[list[Row], list[Row]]:
    base_keys = Counter(_row_key(row) for row in base)
    head_keys = Counter(_row_key(row) for row in head)
    return _rows_beyond(base, head_keys), _rows_beyond(head, base_keys)


def _rows_beyond(rows: Sequence[Row], other: Counter[str]) -> list[Row]:
    remaining = Counter(other)
    extra: list[Row] = []
    for row in rows:
        key = _row_key(row)
        if remaining[key]:
            remaining[key] -= 1
        else:
            extra.append(row)
    return extra


def _row_key(value: Any) -> str:
    if isinstance(value, float):
        return "nan" if math.isnan(value) else f"{value:.9g}"
    if isinstance(value, (list, tuple)):
        return "(" + ",".join(_row_key(item) for item in value) + ")"
    return repr(value)


def load_read_bytes(run_id: str) -> dict[str, int]:
    rows = sync_execute(
        """
        SELECT query_id, max(read_bytes)
        FROM clusterAllReplicas(%(cluster)s, system, query_log)
        WHERE event_date >= yesterday() AND type = 'QueryFinish' AND is_initial_query AND query_id LIKE %(pattern)s
        GROUP BY query_id
        """,
        {"cluster": settings.CLICKHOUSE_CLUSTER, "pattern": f"%replay-{run_id}-%"},
        workload=Workload.OFFLINE,
        readonly=True,
    )
    read_bytes: dict[str, int] = {}
    for query_id, value in rows:
        tag = _TAG.search(query_id)
        if tag:
            read_bytes[tag.group()] = value
    return read_bytes


def run_replay(
    sample: Sequence[LoggedQuery],
    base: Mapping[str, CompiledQuery],
    head: Mapping[str, CompiledQuery],
    execute: Execute = execute_on_clickhouse,
    *,
    run_id: str | None = None,
    max_executed: int = MAX_EXECUTED,
) -> list[Outcome]:
    run_id = run_id or uuid.uuid4().hex
    executed = 0

    def counted(sql: str, team_id: int, tag: str) -> RunResult:
        nonlocal executed
        executed += tag.endswith("-base")
        return execute(sql, team_id, tag)

    return [
        _judge(
            logged,
            base.get(logged.query_id),
            head.get(logged.query_id),
            counted if executed < max_executed else None,
            f"replay-{run_id}-{index}",
        )
        for index, logged in enumerate(sample)
    ]


def _judge(
    logged: LoggedQuery,
    base: CompiledQuery | None,
    head: CompiledQuery | None,
    execute: Execute | None,
    tag: str,
) -> Outcome:
    base_sql = base.sql if base else None
    head_sql = head.sql if head else None

    def outcome(verdict: Verdict, **fields: Any) -> Outcome:
        return Outcome(logged=logged, verdict=verdict, base_sql=base_sql, head_sql=head_sql, **fields)

    if base_sql is None or normalize_sql(base_sql) != normalize_sql(logged.prod_sql):
        return outcome(Verdict.COULD_NOT_MODEL, error=base.error if base else None)
    if head_sql is None:
        return outcome(Verdict.HEAD_ONLY_ERROR, error=head.error if head else "Missing from the head compile")
    if base_sql == head_sql:
        return outcome(Verdict.IDENTICAL_SQL)
    if execute is None:
        return outcome(Verdict.NOT_RUN, error="Over the execution cap")

    base_tag, head_tag = f"{tag}-base", f"{tag}-head"
    first = execute(base_sql, logged.team_id, base_tag)
    if first.error:
        return outcome(Verdict.NOT_RUN, error=first.error)
    second = execute(base_sql, logged.team_id, f"{tag}-base2")
    if not results_match(first, second):
        return outcome(Verdict.UNSTABLE, error=second.error, base_rows=first.row_count)
    result = execute(head_sql, logged.team_id, head_tag)
    tags = {"base_rows": first.row_count, "base_tag": base_tag, "head_tag": head_tag}
    if result.error:
        return outcome(Verdict.HEAD_ONLY_ERROR, error=result.error, **tags)
    if results_match(first, result):
        return outcome(Verdict.SAME_RESULTS, head_rows=result.row_count, **tags)
    base_only, head_only = row_differences(first.rows or (), result.rows or ())
    return outcome(
        Verdict.DIFFERENT_RESULTS,
        head_rows=result.row_count,
        columns=result.columns,
        base_only=tuple(base_only[:DIFFERENCES_SHOWN]),
        head_only=tuple(head_only[:DIFFERENCES_SHOWN]),
        **tags,
    )


def summarize(outcomes: Sequence[Outcome], read_bytes: Mapping[str, int], base: str, head: str) -> dict:
    queries = []
    for o in outcomes:
        base_bytes = read_bytes.get(o.base_tag or "")
        head_bytes = read_bytes.get(o.head_tag or "")
        ratio = head_bytes / base_bytes if base_bytes and head_bytes is not None else None
        file_stem = "sql/" + _UNSAFE_IN_FILE_NAME.sub("_", o.logged.query_id)
        queries.append(
            {
                "query_id": o.logged.query_id,
                "base_sql_file": f"{file_stem}.base.sql",
                "head_sql_file": f"{file_stem}.head.sql",
                "differences_file": f"{file_stem}.differences.json",
                "team_id": o.logged.team_id,
                "kind": o.logged.kind,
                "verdict": o.verdict.value,
                "error": o.error,
                "query": o.logged.query_json,
                "base_sql": o.base_sql,
                "head_sql": o.head_sql,
                "base_rows": o.base_rows,
                "head_rows": o.head_rows,
                "base_read_bytes": base_bytes,
                "head_read_bytes": head_bytes,
                "bytes_ratio": ratio,
                "regression": ratio is not None and ratio > REGRESSION_FACTOR,
            }
        )
    counts = Counter(q["verdict"] for q in queries)
    return {
        "base": base,
        "head": head,
        "counts": {verdict.value: counts.get(verdict.value, 0) for verdict in Verdict},
        "regressions": sum(1 for q in queries if q["regression"]),
        "queries": queries,
    }


def write_report(summary: dict, outcomes: Sequence[Outcome], out_dir: Path) -> None:
    (out_dir / "sql").mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(summary, indent=2))
    (out_dir / "index.html").write_text(_render_html(summary, outcomes))
    for query, outcome in zip(summary["queries"], outcomes):
        if outcome.base_sql and outcome.head_sql and outcome.base_sql != outcome.head_sql:
            (out_dir / query["base_sql_file"]).write_text(outcome.base_sql)
            (out_dir / query["head_sql_file"]).write_text(outcome.head_sql)
        if outcome.verdict == Verdict.DIFFERENT_RESULTS:
            differences = {
                "columns": outcome.columns,
                "only_in_base": outcome.base_only,
                "only_in_head": outcome.head_only,
            }
            (out_dir / query["differences_file"]).write_text(json.dumps(differences, indent=2, default=str))


def _render_html(summary: dict, outcomes: Sequence[Outcome]) -> str:
    def cell(value: object) -> str:
        return f"<td>{html.escape(str(value))}</td>"

    counts = "".join(f"<tr>{cell(verdict)}{cell(count)}</tr>" for verdict, count in summary["counts"].items())
    interesting = [
        (q, o)
        for q, o in zip(summary["queries"], outcomes)
        if q["verdict"] in (Verdict.DIFFERENT_RESULTS, Verdict.HEAD_ONLY_ERROR) or q["regression"]
    ]
    shown = {q["query_id"] for q, _ in interesting}
    other = [q for q in summary["queries"] if q["query_id"] not in shown and q["verdict"] != Verdict.IDENTICAL_SQL]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>HogQL replay</title>
<style>body{{font-family:sans-serif;margin:2rem}}pre{{background:#f4f4f4;padding:1rem;overflow-x:auto}}
td,th{{border:1px solid #ccc;padding:.25rem .5rem;text-align:left}}table{{border-collapse:collapse}}</style></head><body>
<h1>HogQL replay</h1>
<p>Base {html.escape(summary["base"])}, head {html.escape(summary["head"])}.
Queries with identical SQL were not run. Changes to how a query runner shapes its response in Python are not checked.</p>
<table><tr><th>Verdict</th><th>Queries</th></tr>{counts}
<tr>{cell("Reads over " + str(REGRESSION_FACTOR) + " times the bytes")}{cell(summary["regressions"])}</tr></table>
<h2>Changed results, new errors, and higher cost</h2>
{"".join(_render_query(q, o) for q, o in interesting) or "<p>None.</p>"}
<h2>Not judged</h2>
<table><tr><th>Query ID</th><th>Team</th><th>Kind</th><th>Verdict</th><th>Reason</th></tr>
{"".join(f"<tr>{cell(q['query_id'])}{cell(q['team_id'])}{cell(q['kind'])}{cell(q['verdict'])}{cell(q['error'] or '')}</tr>" for q in other)}
</table></body></html>"""


def _render_query(query: dict, outcome: Outcome) -> str:
    diff = "\n".join(
        difflib.unified_diff(
            (query["base_sql"] or "").splitlines(), (query["head_sql"] or "").splitlines(), "base", "head", lineterm=""
        )
    )
    facts = {
        "Verdict": query["verdict"],
        "Team": query["team_id"],
        "Kind": query["kind"],
        "Rows": f"{query['base_rows']} base, {query['head_rows']} head",
        "Bytes read": f"{query['base_read_bytes']} base, {query['head_read_bytes']} head",
        "Error": query["error"] or "",
        "Base SQL": query["base_sql_file"],
        "Head SQL": query["head_sql_file"],
    }
    rows = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>" for k, v in facts.items())
    return (
        f"<h3>{html.escape(query['query_id'])}</h3><table>{rows}</table>"
        f"{_render_rows('Rows only in base', outcome.columns, outcome.base_only)}"
        f"{_render_rows('Rows only in head', outcome.columns, outcome.head_only)}"
        f"<pre>{html.escape(query['query'])}</pre><pre>{html.escape(diff)}</pre>"
    )


def _render_rows(title: str, columns: Sequence[tuple[str, str]], rows: Sequence[Row]) -> str:
    if not rows:
        return ""
    header = "".join(f"<th>{html.escape(name)}</th>" for name, _ in columns)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in row) + "</tr>" for row in rows)
    return f"<h4>{html.escape(title)} (first {DIFFERENCES_SHOWN})</h4><table><tr>{header}</tr>{body}</table>"


def upload(path: Path, key: str) -> None:
    files = [path] if path.is_file() else sorted(file for file in path.rglob("*") if file.is_file())
    for file in files:
        file_key = key if path.is_file() else f"{key}/{file.relative_to(path).as_posix()}"
        content_type = _CONTENT_TYPES.get(file.suffix, "text/plain")
        object_storage.write(file_key, file.read_bytes(), extras={"ContentType": content_type})


def download(key: str, path: Path) -> None:
    content = object_storage.read_bytes(key)
    if content is None:
        raise FileNotFoundError(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
