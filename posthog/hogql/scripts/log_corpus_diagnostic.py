# ruff: noqa: T201, E402
"""HogQL log-corpus parser-parity diagnostic.

Pulls the last 7 days of HogQL queries run against production
ClickHouse by any team that has opted into AI data processing
(`log_comment.ai_data_processing_approved`), runs both the oracle and
candidate parsers over each, and reports where they disagree.

Sibling of `hog_corpus_diagnostic.py` (which does the same for Hog
*programs* from Postgres). Both are real-usage complements to
`pbt_diagnostic.py`'s grammar-generated surface; the Metabase access,
paginated download, parity grind and failure report are shared via
`_diagnostic_common.py`.

## Pipeline

1. **Auto-discover the ClickHouse database id** via
   `hogli metabase:databases`, preferring an `OFFLINE` shard so the
   `system.query_log` scan goes to the background-workload cluster.
2. **Download a redacted dump** via `hogli metabase:query` to the
   gitignored `posthog/hogql/scripts/.local/hogql_log_corpus.json`.
   The embedded SQL applies a chain of `replaceRegexpAll` redaction
   passes (emails, UUIDs, IPv4/6, PostHog API tokens, plus
   defence-in-depth passes for JWT / Stripe / AWS / GitHub / Slack
   credentials, and a broad hex catch-all). Metabase caps responses at
   2000 rows, so larger pulls are paged.
3. **Skip the download** with `--skip-download` to reuse an existing
   dump when iterating on a candidate parser locally.
4. **For each unique query**: parse with `--oracle` (default
   `cpp-json`); oracle reject → skipped. Otherwise parse with
   `--candidate` — reject, crash, AST mismatch, or pass. ASTs are
   compared with per-node `start` / `end` positions by default
   (`CLEAR_LOCATIONS=1` strips them for structural-only comparison).

## Usage

    # Default — auto-discover, download, run cpp-vs-rust parity:
    PYTHONPATH=. python posthog/hogql/scripts/log_corpus_diagnostic.py

    # Iterate on a candidate parser without re-pulling the corpus:
    PYTHONPATH=. python posthog/hogql/scripts/log_corpus_diagnostic.py \\
        --skip-download \\
        --candidate rust-backtrack-json \\
        --write-failures /tmp/rust-backtrack-log-fails.sql
"""

from __future__ import annotations

import os
import sys
import argparse
import traceback
import subprocess
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.hogql.scripts._diagnostic_common import (
    _probe_backend,
    discover_metabase_db,
    download_corpus,
    load_corpus_rows,
    print_corpus_summary,
    repo_relative,
    run_corpus_parity,
    shrink_failures,
    write_failures,
)

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


def _build_corpus_sql(limit: int, offset: int = 0) -> str:
    """Build the corpus query. `limit`/`offset` page the scan; the
    `ORDER BY` carries `hogql` as a tiebreaker so pagination is a stable
    total order (occurrence count alone has ties)."""
    return f"""
SELECT
    {_build_redaction_expr()} AS hogql,
    count() AS n_occurrences
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_time > now() - INTERVAL 7 DAY
  AND type = 'QueryFinish'
  AND is_initial_query
  -- Only teams that have opted into AI data processing — this widens
  -- the corpus beyond PostHog's own team 2 to any consenting team's
  -- real HogQL, while keeping queries from non-consenting teams out.
  AND JSONExtractString(log_comment, 'ai_data_processing_approved') = 'true'
  AND JSONExtractString(log_comment, 'query', 'kind') = 'HogQLQuery'
  AND length(JSONExtractString(log_comment, 'query', 'query')) > 0
GROUP BY hogql
ORDER BY n_occurrences DESC, hogql
LIMIT {int(limit)} OFFSET {int(offset)}
SETTINGS log_comment = '{_LOG_COMMENT_TAG}'
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--region", choices=("us", "eu", "dev"), default="us", help="Metabase region (default: us)")
    p.add_argument(
        "--database-id",
        type=int,
        default=None,
        help="ClickHouse Metabase DB id. Default: auto-discover, preferring OFFLINE shards.",
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
        help=f"Path to the redacted JSON dump (default: {repo_relative(DEFAULT_DUMP, REPO_ROOT)})",
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
        default=os.environ.get("CANDIDATE_BACKEND", "rust-json"),
        help="Backend under test (default: rust-json; override for forks)",
    )
    p.add_argument(
        "--write-failures",
        metavar="PATH",
        default=None,
        help="Output file for failing queries (default: <dump>.failures.sql alongside the dump)",
    )
    p.add_argument(
        "--shrink-failures",
        action="store_true",
        help=(
            "Reduce each failing query to a minimal repro via shrinkray before "
            "writing it out. Needs the optional `hogql-parser-parity` group "
            "(`uv sync --group hogql-parser-parity`)."
        ),
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
    p.add_argument("--verbose", action="store_true", help="Print one line per AST mismatch")
    args = p.parse_args()
    if args.limit is not None and args.limit <= 0:
        p.error("--limit must be a positive integer")

    # Fail fast on a bad backend name.
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
                args.database_id = discover_metabase_db(
                    args.region,
                    "clickhouse",
                    REPO_ROOT,
                    prefer_name_substring=None if args.prefer_online else "offline",
                )
            except subprocess.CalledProcessError as e:
                print(f"ERROR: `hogli metabase:databases` failed (exit {e.returncode})")
                print(f"  hint: run `./bin/hogli metabase:login --region {args.region}` first")
                return 1
            except subprocess.TimeoutExpired:
                print("ERROR: `hogli metabase:databases` timed out after 60s")
                return 1
        else:
            print(f"Using --database-id {args.database_id}")
        sql_limit = args.limit if args.limit and args.limit < _DEFAULT_SQL_LIMIT else _DEFAULT_SQL_LIMIT
        try:
            download_corpus(args.region, args.database_id, args.input, sql_limit, _build_corpus_sql, REPO_ROOT)
        except subprocess.CalledProcessError as e:
            print(f"ERROR: `hogli metabase:query` failed (exit {e.returncode})")
            return 1
        except subprocess.TimeoutExpired:
            print("ERROR: `hogli metabase:query` timed out — narrow the scan with --limit, or retry")
            return 1

    # 2. Load.
    rows = load_corpus_rows(args.input, text_col="hogql", count_col="n_occurrences")
    print(f"Loaded {len(rows)} unique queries from {repo_relative(args.input, REPO_ROOT)}")
    if args.limit is not None and args.limit < len(rows):
        rows = rows[: args.limit]
        print(f"  (capped to first {args.limit} via --limit)")

    # 3. Parity grind.
    print()
    print("Running parity check (oracle then candidate per query)…")
    print()
    result = run_corpus_parity(
        rows,
        rule="select",
        oracle=args.oracle,
        candidate=args.candidate,
        verbose=args.verbose,
        noun="query",
    )
    print_corpus_summary(result, oracle=args.oracle, candidate=args.candidate)

    # 4. Failure dump.
    failures = result.failures
    if failures and args.shrink_failures:
        print()
        print(f"Shrinking {len(failures)} failing queries via shrinkray…")
        failures = shrink_failures(failures, rule="select", oracle=args.oracle, candidate=args.candidate)
    if failures:
        out_path = Path(args.write_failures) if args.write_failures else args.input.with_suffix(".failures.sql")
        write_failures(out_path, failures, REPO_ROOT, title="hogql_log_corpus_failures.sql")
        print()
        print(f"Wrote {len(failures)} failing queries to {repo_relative(out_path, REPO_ROOT)}")

    return 130 if result.interrupted else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
