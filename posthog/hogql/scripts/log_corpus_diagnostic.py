# ruff: noqa: T201, E402
"""HogQL log-corpus parser-parity diagnostic.

Pulls the last 7 days of HogQL queries that team_id=2 (PostHog's own
internal team) ran against production ClickHouse, runs both the oracle
and candidate parsers over each, and reports where they disagree.

Complement to `pbt_diagnostic.py`: that grinds randomly-generated
grammar surface (what HogQL *permits*); this runs over real HogQL
source text as the product emits it (what production *uses*) — insight
queries, hand-rolled HogQL panels, warehouse view materialisation, and
whatever Cloud users trigger via the API. Both are worth running.

## Pipeline

1. **Auto-discover the ClickHouse database id** via
   `hogli metabase:databases --region us --format json`, preferring a
   DB whose name contains `OFFLINE` so the `system.query_log` scan goes
   to the background-workload cluster, not the live one.
2. **Download a redacted dump** via `hogli metabase:query --format json`
   to the gitignored `posthog/hogql/scripts/.local/hogql_log_corpus.json`.
   JSON not TSV — Metabase's TSV writer doesn't escape embedded
   newlines and HogQL queries are routinely multi-line. The embedded
   SQL applies a chain of `replaceRegexpAll` redaction passes (emails,
   UUIDs, IPv4/6, PostHog API tokens, plus defence-in-depth passes for
   JWT / Stripe / AWS / GitHub / Slack credentials, and a broad hex
   catch-all).
3. **Skip the download** with `--skip-download` to reuse an existing
   dump when iterating on a candidate parser locally.
4. **For each unique query**: parse with `--oracle` (default
   `cpp-json`); oracle reject → skipped. Otherwise parse with
   `--candidate` — reject, crash (non-HogQL exception), AST mismatch,
   or pass. ASTs are compared after `clear_locations()`.

## Usage

    # Default — auto-discover, download, run cpp-vs-python parity:
    PYTHONPATH=. python posthog/hogql/scripts/log_corpus_diagnostic.py

    # Iterate on a candidate parser without re-pulling the corpus:
    PYTHONPATH=. python posthog/hogql/scripts/log_corpus_diagnostic.py \\
        --skip-download \\
        --candidate rust-backtrack-json \\
        --write-failures /tmp/rust-backtrack-log-fails.sql

    # Override the dump path entirely:
    PYTHONPATH=. python posthog/hogql/scripts/log_corpus_diagnostic.py \\
        --input /some/other/dump.json
"""

from __future__ import annotations

import os
import re
import sys
import json
import signal
import argparse
import traceback
import subprocess
import dataclasses
from collections import Counter
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.scripts._diagnostic_common import _GOT_RE, _diff_path, _format_diff_path, _node_type, _probe_backend
from posthog.hogql.visitor import clear_locations

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DUMP = REPO_ROOT / "posthog" / "hogql" / "scripts" / ".local" / "hogql_log_corpus.json"


# ---------------------------------------------------------------------------
# Embedded SQL — keep the source of the corpus reproducible from the script
# ---------------------------------------------------------------------------

_DEFAULT_SQL_LIMIT = 10000

# Stamped into our own `log_comment` so this scan is attributable in
# `system.query_log` rather than an anonymous ad-hoc Metabase query.
_LOG_COMMENT_TAG = '{"source": "hogql_log_corpus_diagnostic"}'

# Redaction passes over the HogQL text, applied in list order (each
# wraps the previous). Order matters: email before the hex/IPv6 passes
# that would otherwise eat `@`-content; specific token shapes before
# the broad `[a-fA-F0-9]{32,}` catch-all; IPv6 before IPv4. Patterns
# are re2 source — `_build_redaction_expr` escapes them for SQL.
_REDACTION_PASSES: list[tuple[str, str]] = [
    (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "<email>"),
    # UUID — case-insensitive (raw user HogQL needn't be lowercase).
    (
        r"[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}",
        "<uuid>",
    ),
    # PostHog API tokens: phc_/phx_/phs_ today, any future ph?_ prefix.
    (r"\bph[a-z]_[A-Za-z0-9]{10,}", "<ph_token>"),
    # Credential shapes below ~never appear in HogQL text — kept as
    # defence-in-depth against a stray paste reaching the dump.
    (r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+", "<jwt>"),
    (r"\b[sprk]k_(live|test)_[A-Za-z0-9]{10,}", "<stripe_key>"),
    (r"\b(AKIA|ASIA)[A-Z0-9]{16}\b", "<aws_key>"),
    (r"\bgh[posru]_[A-Za-z0-9]{30,}", "<gh_token>"),
    (r"\bgithub_pat_[A-Za-z0-9_]{20,}", "<gh_token>"),
    (r"\bxox[bpoars]-[A-Za-z0-9-]{10,}", "<slack_token>"),
    # IPv6 — 4+ colon-separated hex groups, so `HH:MM:SS` timestamps
    # inside toDateTime() literals don't false-positive.
    (r"([0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{1,4}", "<ipv6>"),
    # IPv4 — `(^|[^.\d])` captures the char before so a `.`-preceded
    # match (e.g. `1.2.3.4` inside the tuple access `t.1.2.3.4`) is
    # skipped; re2 has no lookbehind, so the captured char is re-emitted
    # via the `\1` backreference. A digit prefix is excluded too, to
    # keep the original `\b`-start semantics.
    (r"(^|[^.\d])(\d{1,3}\.){3}\d{1,3}\b", r"\1<ipv4>"),
    # Broad catch-all: 32+ contiguous hex (hashes / opaque ids).
    (r"\b[a-fA-F0-9]{32,}\b", "<hex>"),
]


def _sql_str_literal(s: str) -> str:
    """Escape a string for a ClickHouse single-quoted literal — double
    backslashes, escape quotes. Applied to both the pattern and the
    replacement so `_REDACTION_PASSES` can hold plain re2 source,
    including replacements with `\\1` backreferences."""
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _build_redaction_expr() -> str:
    """Nest `_REDACTION_PASSES` into one `replaceRegexpAll(…)` chain over
    the HogQL column."""
    expr = "JSONExtractString(log_comment, 'query', 'query')"
    for pattern, replacement in _REDACTION_PASSES:
        expr = f"replaceRegexpAll({expr}, '{_sql_str_literal(pattern)}', '{_sql_str_literal(replacement)}')"
    return expr


def _build_redaction_sql(limit: int) -> str:
    """Build the corpus query. `limit` caps the scan at the SQL level so
    quick `--limit 50` runs don't fetch rows we'll never look at."""
    return f"""
SELECT
    {_build_redaction_expr()} AS hogql,
    count() AS n_occurrences
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_time > now() - INTERVAL 7 DAY
  AND type = 'QueryFinish'
  AND is_initial_query
  AND JSONExtractInt(log_comment, 'team_id') = 2
  AND JSONExtractString(log_comment, 'query', 'kind') = 'HogQLQuery'
  AND length(JSONExtractString(log_comment, 'query', 'query')) > 0
GROUP BY hogql
ORDER BY n_occurrences DESC
LIMIT {int(limit)}
SETTINGS log_comment = '{_LOG_COMMENT_TAG}'
"""


def _repo_relative(path: Path) -> str:
    """Repo-rooted string when `path` is inside `REPO_ROOT`, else
    verbatim — so an out-of-worktree `--input` still prints cleanly."""
    if path.is_absolute() and path.is_relative_to(REPO_ROOT):
        return str(path.relative_to(REPO_ROOT))
    return str(path)


# ---------------------------------------------------------------------------
# hogli wrappers
# ---------------------------------------------------------------------------


def _hogli_bin() -> str:
    """Absolute path to `bin/hogli` — `$PATH` has it under flox for
    interactive shells but agent / CI shells often don't."""
    cand = REPO_ROOT / "bin" / "hogli"
    if not cand.is_file():
        raise RuntimeError(f"bin/hogli not found at {cand} — is the repo root correct?")
    return str(cand)


def _discover_clickhouse_db_id(region: str, prefer_offline: bool) -> int:
    """Return a ClickHouse DB id from Metabase, preferring an `OFFLINE`
    shard when `prefer_offline`. Raises if `hogli metabase:databases`
    fails — usually a missing cookie (`hogli metabase:login` first)."""
    out = subprocess.check_output(
        [_hogli_bin(), "metabase:databases", "--region", region, "--format", "json"],
        cwd=REPO_ROOT,
        text=True,
        timeout=60,  # don't hang forever on a stalled Metabase / auth wait
    )
    dbs = json.loads(out)
    # case-insensitive: Metabase has drifted casing on metadata fields
    clickhouse_dbs = [db for db in dbs if db.get("engine", "").lower() == "clickhouse"]
    if not clickhouse_dbs:
        raise RuntimeError(f"No ClickHouse databases listed for region={region!r}")
    if prefer_offline:
        offline = [db for db in clickhouse_dbs if "offline" in db.get("name", "").lower()]
        if offline:
            # Any OFFLINE shard has the same `clusterAllReplicas` reach;
            # sort by id just for determinism.
            offline.sort(key=lambda d: d["id"])
            chosen = offline[0]
            print(f"  using OFFLINE ClickHouse db id={chosen['id']} name={chosen['name']!r}")
            return int(chosen["id"])
        print("  no OFFLINE ClickHouse DB matched; falling back to first online")
    chosen = sorted(clickhouse_dbs, key=lambda d: d["id"])[0]
    print(f"  using ClickHouse db id={chosen['id']} name={chosen['name']!r}")
    return int(chosen["id"])


def _download_corpus(region: str, database_id: int, dump_path: Path, sql_limit: int) -> None:
    """Run the redaction SQL via `hogli metabase:query`, saving the JSON
    response to `dump_path` (shape: see `_load_queries`).

    hogli writes to a `.tmp` sibling we then `os.replace` into place —
    an interrupted scan can't leave a half-written dump that a later
    `--skip-download` would silently read as truncated JSON."""
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dump_path.with_suffix(dump_path.suffix + ".tmp")
    print(f"  downloading top {sql_limit} via `hogli metabase:query --region {region} --database-id {database_id}` …")
    try:
        subprocess.run(
            [
                _hogli_bin(),
                "metabase:query",
                "--region",
                region,
                "--database-id",
                str(database_id),
                "--format",
                "json",
                "--save",
                str(tmp_path),
                # SQL goes over stdin; `--timeout` covers the slow query_log scan.
                "--timeout",
                "300",
            ],
            input=_build_redaction_sql(sql_limit),
            text=True,
            check=True,
            cwd=REPO_ROOT,
            timeout=360,  # process-level backstop above hogli's own `--timeout 300`
        )
        os.replace(tmp_path, dump_path)
    finally:
        tmp_path.unlink(missing_ok=True)  # no-op after a successful replace
    print(f"  saved {dump_path.stat().st_size:,} bytes to {_repo_relative(dump_path)}")


# ---------------------------------------------------------------------------
# JSON reader
# ---------------------------------------------------------------------------


def _load_queries(path: Path) -> list[tuple[str, int]]:
    """Read the JSON from `hogli metabase:query --format json` into
    `(hogql, n_occurrences)` pairs, skipping empty HogQL. Columns are
    resolved by name (`{"data": {"cols": [...], "rows": [...]}}`) so the
    reader survives column-order changes in the embedded SQL."""
    if not path.exists():
        raise FileNotFoundError(
            f"corpus dump not found at {path}\n  hint: drop --skip-download to fetch it from Metabase, or pass --input PATH"
        )
    with open(path) as f:
        payload = json.load(f)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not data or "rows" not in data or "cols" not in data:
        status = payload.get("status") if isinstance(payload, dict) else "<unknown>"
        error = payload.get("error") if isinstance(payload, dict) else None
        raise RuntimeError(
            f"dump at {path} isn't a Metabase /api/dataset success payload (status={status!r}, error={error!r})"
        )
    col_idx = {c.get("name"): i for i, c in enumerate(data["cols"])}
    if "hogql" not in col_idx:
        raise RuntimeError(
            f"dump columns {list(col_idx)} don't include 'hogql' — re-run without --skip-download to refresh the dump"
        )
    hogql_i = col_idx["hogql"]
    n_i = col_idx.get("n_occurrences")
    out: list[tuple[str, int]] = []
    for row in data["rows"]:
        query = row[hogql_i]
        if not isinstance(query, str) or not query.strip():
            continue
        n = 1
        if n_i is not None:
            try:
                n = int(row[n_i])
            except (TypeError, ValueError):
                n = 1
        out.append((query, n))
    return out


# ---------------------------------------------------------------------------
# Parser dispatch
# ---------------------------------------------------------------------------


def _try_parse(query: str, backend: str) -> tuple[str, ast.AST | None, str | None]:
    """Parse `query` with `backend`. Returns `(status, ast_or_none, detail)`:

    - `("ok", ast, None)` — parsed; AST is `clear_locations`-normalised
      so callers can `==`-compare oracle vs candidate.
    - `("reject", None, error)` — backend declined it (`BaseHogQLError`).
    - `("crash", None, traceback)` — backend raised something else
      (`RecursionError`, …). A crash is itself a finding worth
      recording, so we bucket it rather than abort the run. Ctrl-C
      (`BaseException`, not `Exception`) still propagates."""
    try:
        node = parse_select(query, backend=backend)  # type: ignore[arg-type]
        return "ok", clear_locations(node), None
    except BaseHogQLError as e:
        return "reject", None, str(e)
    except Exception:
        return "crash", None, traceback.format_exc()


# ---------------------------------------------------------------------------
# Error bucketing
# ---------------------------------------------------------------------------

# `_GOT_RE` is shared with the other diagnostic scripts; `_AT_RE` is local —
# only this script's `_bucket_error` strips position suffixes.
_AT_RE = re.compile(r"at\s+(line\s+\d+|offset\s+\d+|position\s+\d+|\d+:\d+)", re.IGNORECASE)


def _bucket_error(msg: str) -> str:
    """Normalise an error message so same-cause rejects group together —
    drops position-dependent suffixes (`got <X>`, `at line N`), clips
    to 160 chars."""
    msg = _GOT_RE.sub("got <X>", msg)
    msg = _AT_RE.sub("at <pos>", msg)
    return msg.strip()[:160]


def _crash_signature(tb: str) -> str:
    """Bucket a crash by its traceback's last line (the
    `ExceptionType: message`) so same-cause crashes group together."""
    lines = [ln for ln in tb.splitlines() if ln.strip()]
    return _bucket_error(lines[-1]) if lines else "<empty traceback>"


# ---------------------------------------------------------------------------
# Failure file writer
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Failure:
    """Single failing-query record for the failure file."""

    # "candidate_reject" | "candidate_crash" | "ast_mismatch" | "oracle_crash"
    kind: str
    query: str
    detail: str  # rejection error, crash traceback, or formatted diff path
    n_occurrences: int


def _write_failures(path: Path, failures: list[Failure]) -> None:
    """One block per failing query, separated by a `-- =====` ruler,
    carrying the rejection error / crash traceback / AST diff path so a
    follow-up triage pass can bucket by root cause. Written via a
    `.tmp` sibling + `os.replace` so a crash mid-write can't leave a
    truncated file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    by_kind = Counter(fa.kind for fa in failures)
    breakdown = ", ".join(f"{n} {kind}" for kind, n in sorted(by_kind.items())) or "none"
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w") as f:
        f.write(f"-- hogql_log_corpus_failures.sql — {len(failures)} entries\n")
        f.write(f"-- ({breakdown})\n")
        f.write("-- Each block: occurrences count, failure kind + detail, then the query.\n")
        f.write("-- Generated by posthog/hogql/scripts/log_corpus_diagnostic.py\n\n")
        for i, fa in enumerate(failures):
            f.write("-- " + "=" * 76 + "\n")
            f.write(f"-- [{i + 1}/{len(failures)}] seen {fa.n_occurrences}x in last 7d\n")
            f.write(f"-- kind: {fa.kind}\n")
            for line in fa.detail.splitlines() or [""]:
                f.write(f"-- {line}\n" if line else "--\n")
            f.write("\n")
            f.write(fa.query.rstrip("\n") + "\n\n")
    os.replace(tmp_path, path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--region",
        choices=("us", "eu", "dev"),
        default="us",
        help="Metabase region (default: us; team 2 is PostHog's own US team)",
    )
    p.add_argument(
        "--database-id",
        type=int,
        default=None,
        help="ClickHouse Metabase DB id. Default: auto-discover via `hogli metabase:databases`, preferring OFFLINE shards.",
    )
    p.add_argument(
        "--prefer-online",
        action="store_true",
        help="Override the default OFFLINE-preference during auto-discovery (don't do this unless you know why).",
    )
    p.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_DUMP,
        help=f"Path to the redacted JSON dump (default: {_repo_relative(DEFAULT_DUMP)})",
    )
    p.add_argument(
        "--skip-download",
        action="store_true",
        help="Reuse the existing JSON dump at --input rather than re-running the Metabase query",
    )
    p.add_argument(
        "--oracle",
        default=os.environ.get("ORACLE_BACKEND", "cpp-json"),
        help="Source-of-truth backend (default: cpp-json)",
    )
    p.add_argument(
        "--candidate",
        default=os.environ.get("CANDIDATE_BACKEND", "python"),
        help="Backend under test (default: python; override for forks)",
    )
    p.add_argument(
        "--write-failures",
        metavar="PATH",
        default=None,
        help="Output file for SQLs the candidate rejects (default: <dump>.failures.sql alongside the dump)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            f"Cap to first N unique queries (for fast iteration). When downloading, the SQL's "
            f"`LIMIT` is set to N as well so the Metabase round-trip stays fast; without --limit "
            f"we pull up to {_DEFAULT_SQL_LIMIT} rows."
        ),
    )
    p.add_argument("--verbose", action="store_true", help="Print one line per failure / skip with the error")
    args = p.parse_args()
    if args.limit is not None and args.limit <= 0:
        p.error("--limit must be a positive integer")

    # Fail fast on a bad backend name — `_probe_backend` bypasses the
    # `except Exception` in `_try_parse` that would swallow a typo's `KeyError`.
    for label, backend in (("oracle", args.oracle), ("candidate", args.candidate)):
        err = _probe_backend("select", backend)
        if err is not None:
            print(f"ERROR: {label} backend {backend!r} unavailable: {err}")
            return 1

    if args.oracle == args.candidate:
        print(
            f"WARNING: --oracle and --candidate are both {args.oracle!r} — "
            f"this is not a parity check; every query will trivially 'pass'."
        )

    print(f"=== HogQL log-corpus diagnostic: oracle={args.oracle} candidate={args.candidate} ===")
    print()

    # 1. Acquire the dump.
    if args.skip_download:
        if not args.input.exists():
            print(f"ERROR: --skip-download but no dump at {args.input}")
            print("  drop --skip-download to fetch it, or pass --input PATH to point at an existing dump")
            return 1
        print(f"Reusing existing dump: {args.input}")
    else:
        print(f"Region: {args.region}")
        if args.database_id is None:
            print("Auto-discovering ClickHouse DB id …")
            try:
                args.database_id = _discover_clickhouse_db_id(args.region, prefer_offline=not args.prefer_online)
            except subprocess.CalledProcessError as e:
                print(f"ERROR: `hogli metabase:databases` failed (exit {e.returncode})")
                print(f"  hint: run `./bin/hogli metabase:login --region {args.region}` first")
                return 1
            except subprocess.TimeoutExpired:
                print("ERROR: `hogli metabase:databases` timed out after 60s")
                print(f"  hint: run `./bin/hogli metabase:login --region {args.region}` first")
                return 1
        else:
            print(f"Using --database-id {args.database_id}")
        # `--limit N` also caps the SQL `LIMIT` so quick runs stay fast.
        sql_limit = args.limit if args.limit and args.limit < _DEFAULT_SQL_LIMIT else _DEFAULT_SQL_LIMIT
        try:
            _download_corpus(args.region, args.database_id, args.input, sql_limit)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: `hogli metabase:query` failed (exit {e.returncode})")
            return 1
        except subprocess.TimeoutExpired:
            print("ERROR: `hogli metabase:query` timed out after 360s")
            print("  hint: narrow the scan with --limit, or retry — the query_log scan can be slow")
            return 1

    # 2. Load.
    rows = _load_queries(args.input)
    print(f"Loaded {len(rows)} unique queries from {_repo_relative(args.input)}")
    if args.limit is not None and args.limit < len(rows):
        rows = rows[: args.limit]
        print(f"  (capped to first {args.limit} via --limit)")

    # 3. Parity grind.
    print()
    print("Running parity check (oracle then candidate per query)…")
    print()
    counts: Counter[str] = Counter()
    reject_buckets: Counter[str] = Counter()
    crash_buckets: Counter[str] = Counter()
    mismatch_buckets: Counter[tuple[str, str]] = Counter()
    oracle_reject_buckets: Counter[str] = Counter()
    failures: list[Failure] = []

    # Flush partial results on Ctrl-C: a grind over thousands of
    # queries takes minutes, and the failure file is the whole point
    # of the run. A SIGINT sets a flag the loop checks at the next
    # iteration boundary, so the summary + failure dump below still
    # run against whatever was accumulated rather than being lost.
    interrupted = False

    def _on_sigint(_signum: int, _frame: object) -> None:
        nonlocal interrupted
        interrupted = True

    prev_sigint = signal.signal(signal.SIGINT, _on_sigint)

    for i, (query, n_occ) in enumerate(rows):
        if interrupted:
            print(f"\nInterrupted at {i}/{len(rows)} — writing partial results…")
            break
        if (i + 1) % 50 == 0:
            sys.stderr.write(
                f"\r  {i + 1}/{len(rows)} processed (pass={counts['pass']} reject={counts['candidate_reject']} "
                f"mismatch={counts['ast_mismatch']} crash={counts['candidate_crash'] + counts['oracle_crash']} "
                f"skip={counts['oracle_reject']})"
            )
            sys.stderr.flush()
        counts["total"] += 1
        oracle_status, oracle_ast, oracle_detail = _try_parse(query, args.oracle)
        if oracle_status == "reject":
            counts["oracle_reject"] += 1
            sig = _bucket_error(oracle_detail or "")
            oracle_reject_buckets[sig] += 1
            if args.verbose:
                print(f"  SKIP: {sig}")
            continue
        if oracle_status == "crash":
            # Oracle crash is a finding too; record it, but with no
            # oracle AST there's nothing to compare — skip the candidate.
            counts["oracle_crash"] += 1
            crash_buckets[_crash_signature(oracle_detail or "")] += 1
            failures.append(
                Failure(
                    kind="oracle_crash",
                    query=query,
                    detail=oracle_detail or "<no traceback>",
                    n_occurrences=n_occ,
                )
            )
            if args.verbose:
                print(f"  ORACLE CRASH (seen {n_occ}x): {_crash_signature(oracle_detail or '')}")
            continue
        candidate_status, candidate_ast, candidate_detail = _try_parse(query, args.candidate)
        if candidate_status == "reject":
            counts["candidate_reject"] += 1
            sig = _bucket_error(candidate_detail or "")
            reject_buckets[sig] += 1
            failures.append(
                Failure(
                    kind="candidate_reject",
                    query=query,
                    detail=candidate_detail or "<no message>",
                    n_occurrences=n_occ,
                )
            )
            if args.verbose:
                print(f"  REJECT (seen {n_occ}x): {sig}")
            continue
        if candidate_status == "crash":
            counts["candidate_crash"] += 1
            sig = _crash_signature(candidate_detail or "")
            crash_buckets[sig] += 1
            failures.append(
                Failure(
                    kind="candidate_crash",
                    query=query,
                    detail=candidate_detail or "<no traceback>",
                    n_occurrences=n_occ,
                )
            )
            if args.verbose:
                print(f"  CANDIDATE CRASH (seen {n_occ}x): {sig}")
            continue
        if oracle_ast == candidate_ast:
            counts["pass"] += 1
            continue
        counts["ast_mismatch"] += 1
        steps = _diff_path(oracle_ast, candidate_ast)
        bucket = (_node_type(oracle_ast), _node_type(candidate_ast))
        mismatch_buckets[bucket] += 1
        failures.append(
            Failure(
                kind="ast_mismatch",
                query=query,
                detail=_format_diff_path(steps),
                n_occurrences=n_occ,
            )
        )
        if args.verbose:
            print(f"  MISMATCH (seen {n_occ}x): {bucket[0]} vs {bucket[1]}")

    signal.signal(signal.SIGINT, prev_sigint)
    sys.stderr.write("\r" + " " * 110 + "\r")

    # 4. Summary.
    print()
    print("=== Summary ===")
    for k in ("total", "pass", "candidate_reject", "candidate_crash", "ast_mismatch", "oracle_crash", "oracle_reject"):
        print(f"  {k:25s} {counts[k]}")

    if oracle_reject_buckets:
        print()
        print(f"=== Oracle ({args.oracle}) reject buckets ({sum(oracle_reject_buckets.values())} total) ===")
        for sig, n in oracle_reject_buckets.most_common(20):
            print(f"  {n:5d}  {sig}")
        if len(oracle_reject_buckets) > 20:
            print(f"  … and {len(oracle_reject_buckets) - 20} more buckets")

    if reject_buckets:
        print()
        print(f"=== Candidate ({args.candidate}) reject buckets ({sum(reject_buckets.values())} total) ===")
        for sig, n in reject_buckets.most_common(30):
            print(f"  {n:5d}  {sig}")
        if len(reject_buckets) > 30:
            print(f"  … and {len(reject_buckets) - 30} more buckets")

    if crash_buckets:
        print()
        print(f"=== Crash buckets ({sum(crash_buckets.values())} total — non-HogQL exceptions) ===")
        for sig, n in crash_buckets.most_common(30):
            print(f"  {n:5d}  {sig}")
        if len(crash_buckets) > 30:
            print(f"  … and {len(crash_buckets) - 30} more buckets")

    if mismatch_buckets:
        print()
        print(f"=== AST mismatch buckets ({sum(mismatch_buckets.values())} total) ===")
        print(f"  {'count':>5}  {'oracle':25s} vs candidate")
        for (o_root, c_root), n in mismatch_buckets.most_common(30):
            print(f"  {n:5d}  {o_root:25s} vs {c_root}")
        if len(mismatch_buckets) > 30:
            print(f"  … and {len(mismatch_buckets) - 30} more buckets")

    # 5. Failure dump.
    if failures:
        out_path = Path(args.write_failures) if args.write_failures else args.input.with_suffix(".failures.sql")
        _write_failures(out_path, failures)
        print()
        print(f"Wrote {len(failures)} failing queries to {_repo_relative(out_path)}")

    return 130 if interrupted else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
