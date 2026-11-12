import re
import html
import json
import uuid
import difflib
import dataclasses
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import time_machine
from unittest.mock import patch

from django.conf import settings

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.escape import substitute_params
from posthog.clickhouse.query_tagging import tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team

SAMPLE_DAYS = 7
SAMPLE_ONE_IN = 100
LOOKUP_DAYS = 30
MAX_EXECUTED = 200
REGRESSION_FACTOR = 1.5
EXECUTION_SETTINGS = {"use_query_condition_cache": 0, "max_execution_time": 60}

_LEADING_COMMENTS = re.compile(r"^(\s*/\*.*?\*/)+", re.DOTALL)
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d+)?")
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


@frozen
class RunResult:
    row_count: int | None = None
    fingerprint: int | None = None
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
    logged = "type = 'QueryFinish' AND is_initial_query AND lc_query__kind != '' AND team_id > 0"
    if query_ids:
        selection = f"event_date >= today() - {LOOKUP_DAYS} AND query_id IN %(query_ids)s"
    else:
        selection = f"""event_date >= today() - {SAMPLE_DAYS} AND query_id IN (
            SELECT query_id FROM query_log_archive
            WHERE event_date >= today() - {SAMPLE_DAYS} AND {logged} AND rand() %% {SAMPLE_ONE_IN} = 0
        )"""
    rows = sync_execute(
        f"""
        SELECT query_id, team_id, lc_query__kind, lc_query, query, query_start_time
        FROM query_log_archive
        WHERE {selection} AND {logged}
        ORDER BY rand()
        LIMIT 1 BY team_id, cityHash64(lc_query)
        LIMIT %(limit)s
        """,
        {"query_ids": list(query_ids), "limit": len(query_ids) or sample_size},
        workload=Workload.OFFLINE,
        readonly=True,
    )
    return [
        LoggedQuery(
            query_id=query_id,
            team_id=team_id,
            kind=kind,
            query_json=query_json,
            prod_sql=prod_sql,
            started_at=started_at.replace(tzinfo=UTC),
        )
        for query_id, team_id, kind, query_json, prod_sql, started_at in rows
    ]


def compile_logged_query(logged: LoggedQuery) -> CompiledQuery:
    captured: list[str] = []

    def record(sql: str, values: Mapping[str, Any] | None = None, **_: Any) -> tuple[list[Any], list[Any]]:
        captured.append(substitute_params(sql, dict(values or {})))
        return [], []

    failure: Exception | None = None
    try:
        with (
            time_machine.travel(logged.started_at, tick=False),
            patch("posthog.hogql.query.sync_execute", side_effect=record),
        ):
            team = Team.objects.get(pk=logged.team_id)
            get_query_runner(query=json.loads(logged.query_json), team=team).calculate()
    except Exception as e:
        failure = e

    if len(captured) == 1:
        return CompiledQuery(query_id=logged.query_id, sql=captured[0])
    if captured:
        return CompiledQuery(query_id=logged.query_id, error=f"Runner issued {len(captured)} statements")
    return CompiledQuery(query_id=logged.query_id, error=repr(failure) if failure else "Runner issued no statement")


def normalize_sql(sql: str) -> str:
    without_comments = _LEADING_COMMENTS.sub("", sql)
    return _TIMESTAMP.sub("<ts>", " ".join(without_comments.split()))


def execute_on_clickhouse(sql: str, team_id: int, tag: str) -> RunResult:
    try:
        with tags_context(client_query_id=tag, team_id=team_id):
            rows = sync_execute(
                f"SELECT count(), sum(cityHash64(toString(tuple(*)))) FROM ({sql})",
                settings=EXECUTION_SETTINGS,
                workload=Workload.OFFLINE,
                team_id=team_id,
                readonly=True,
            )
    except Exception as e:
        return RunResult(error=repr(e))
    return RunResult(row_count=rows[0][0], fingerprint=rows[0][1])


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
    if second != first:
        return outcome(Verdict.UNSTABLE, error=second.error, base_rows=first.row_count)
    result = execute(head_sql, logged.team_id, head_tag)
    tags = {"base_rows": first.row_count, "base_tag": base_tag, "head_tag": head_tag}
    if result.error:
        return outcome(Verdict.HEAD_ONLY_ERROR, error=result.error, **tags)
    verdict = Verdict.SAME_RESULTS if result == first else Verdict.DIFFERENT_RESULTS
    return outcome(verdict, head_rows=result.row_count, **tags)


def summarize(outcomes: Sequence[Outcome], read_bytes: Mapping[str, int], base_sha: str, head_sha: str) -> dict:
    queries = []
    for o in outcomes:
        base_bytes = read_bytes.get(o.base_tag or "")
        head_bytes = read_bytes.get(o.head_tag or "")
        ratio = head_bytes / base_bytes if base_bytes and head_bytes is not None else None
        queries.append(
            {
                "query_id": o.logged.query_id,
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
        "base_sha": base_sha,
        "head_sha": head_sha,
        "counts": {verdict.value: counts.get(verdict.value, 0) for verdict in Verdict},
        "regressions": sum(1 for q in queries if q["regression"]),
        "queries": queries,
    }


def write_report(summary: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(summary, indent=2))
    (out_dir / "index.html").write_text(_render_html(summary))


def _render_html(summary: dict) -> str:
    def cell(value: object) -> str:
        return f"<td>{html.escape(str(value))}</td>"

    counts = "".join(f"<tr>{cell(verdict)}{cell(count)}</tr>" for verdict, count in summary["counts"].items())
    interesting = [
        q
        for q in summary["queries"]
        if q["verdict"] in (Verdict.DIFFERENT_RESULTS, Verdict.HEAD_ONLY_ERROR) or q["regression"]
    ]
    other = [q for q in summary["queries"] if q not in interesting and q["verdict"] != Verdict.IDENTICAL_SQL]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>HogQL replay</title>
<style>body{{font-family:sans-serif;margin:2rem}}pre{{background:#f4f4f4;padding:1rem;overflow-x:auto}}
td,th{{border:1px solid #ccc;padding:.25rem .5rem;text-align:left}}table{{border-collapse:collapse}}</style></head><body>
<h1>HogQL replay</h1>
<p>Base {html.escape(summary["base_sha"])}, head {html.escape(summary["head_sha"])}.
Queries with identical SQL were not run. Changes to how a query runner shapes its response in Python are not checked.</p>
<table><tr><th>Verdict</th><th>Queries</th></tr>{counts}
<tr>{cell("Reads over " + str(REGRESSION_FACTOR) + " times the bytes")}{cell(summary["regressions"])}</tr></table>
<h2>Changed results, new errors, and higher cost</h2>
{"".join(_render_query(q) for q in interesting) or "<p>None.</p>"}
<h2>Not judged</h2>
<table><tr><th>Query ID</th><th>Team</th><th>Kind</th><th>Verdict</th><th>Reason</th></tr>
{"".join(f"<tr>{cell(q['query_id'])}{cell(q['team_id'])}{cell(q['kind'])}{cell(q['verdict'])}{cell(q['error'] or '')}</tr>" for q in other)}
</table></body></html>"""


def _render_query(query: dict) -> str:
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
    }
    rows = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>" for k, v in facts.items())
    return (
        f"<h3>{html.escape(query['query_id'])}</h3><table>{rows}</table>"
        f"<pre>{html.escape(query['query'])}</pre><pre>{html.escape(diff)}</pre>"
    )
