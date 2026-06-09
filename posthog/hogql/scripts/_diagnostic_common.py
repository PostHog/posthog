# ruff: noqa: T201
"""Shared helpers for the HogQL parser-parity diagnostic scripts.

Imported by `pbt_diagnostic.py`, `pbt_corpus.py`, `parser_bench.py`,
and `log_corpus_diagnostic.py` in this directory. Not a CLI itself —
the leading underscore marks it as a private helper module.

Holds the cross-script vocabulary:

- **Parse** — `_safe_parse` parses a query and classifies the outcome
  `ok` / `reject` / `crash`, never propagating a backend crash (a CLI
  diagnostic buckets crashes rather than aborting the grind).
- **AST diff path** — `_node_type` / `_diff_path` / `_format_diff_path`
  walk two ASTs together and pinpoint the first divergence.
- **Divergence shape** — `DivergenceShape` / `_ast_mismatch_shape` /
  `_shape_for` reduce a divergence to a structural key two examples of
  the same bug compare equal under.
- **Error normalisation** — `_normalize_error` strips position-dependent
  payloads so same-cause rejects/crashes bucket together.
- **Backend probe** — `_probe_backend` fails fast on an unusable
  `--oracle` / `--candidate`.

Importing this module pulls `posthog.hogql.*` — callers must have run
`django.setup()` first (every script here does, before its imports).
"""

from __future__ import annotations

import os
import re
import sys
import json
import signal
import traceback
import subprocess
import dataclasses
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import HogQLParserShadowMismatch, parse_expr, parse_program, parse_select
from posthog.hogql.visitor import clear_locations

# Maps a diagnostic `--rule` value to its parser entry point. `program`
# covers the Hog imperative-statement layer (let / if / while / for /
# fn / try-catch / return / throw / blocks).
_PARSER_FOR_RULE: dict[str, Callable[..., Any]] = {
    "expr": parse_expr,
    "select": parse_select,
    "program": parse_program,
}

# ---------------------------------------------------------------------------
# AST diff path
# ---------------------------------------------------------------------------


def _node_type(node: Any) -> str:
    """Top-level AST node type label, e.g. `Call` / `ExprCall` / `Not`."""
    return type(node).__name__ if node is not None else "<None>"


def _node_fields(node: Any) -> list[tuple[str, Any]]:
    """`(field_name, value)` pairs for an AST node in declaration order.
    HogQL AST nodes are `__slots__` dataclasses, so `dataclasses.fields()`
    is the canonical accessor; non-dataclass leaves return `[]` and fall
    through to the value-terminal branch in `_diff_path`."""
    if not dataclasses.is_dataclass(node):
        return []
    return [(f.name, getattr(node, f.name, None)) for f in dataclasses.fields(node)]


def _diff_path(oracle: Any, candidate: Any, path: list | None = None, depth: int = 0) -> list:
    """Walk both ASTs together; return the `.field` / `[i]` breadcrumbs
    from root to the first divergence, terminating with a 3-tuple
    `(label, oracle_repr, candidate_repr)`. Depth-bounded so pathological
    deep trees don't blow the stack."""
    path = path or []
    if depth > 64:
        return [*path, ("<depth-limit>", repr(oracle)[:120], repr(candidate)[:120])]
    if oracle == candidate:
        return path
    o_t = _node_type(oracle)
    c_t = _node_type(candidate)
    if o_t != c_t:
        return [*path, ("<type>", o_t, c_t)]

    if isinstance(oracle, list) and isinstance(candidate, list):
        if len(oracle) != len(candidate):
            return [*path, ("<len>", str(len(oracle)), str(len(candidate)))]
        for i, (a, b) in enumerate(zip(oracle, candidate)):
            if a != b:
                return _diff_path(a, b, [*path, f"[{i}]"], depth + 1)
        return path
    if isinstance(oracle, dict) and isinstance(candidate, dict):
        if set(oracle) != set(candidate):
            return [*path, ("<keys>", str(sorted(oracle)), str(sorted(candidate)))]
        for k in oracle:
            if oracle[k] != candidate[k]:
                return _diff_path(oracle[k], candidate[k], [*path, f"[{k!r}]"], depth + 1)
        return path
    o_fields = _node_fields(oracle)
    c_fields = dict(_node_fields(candidate))
    if o_fields:
        for name, ov in o_fields:
            cv = c_fields.get(name)
            if ov == cv:
                continue
            return _diff_path(ov, cv, [*path, f".{name}"], depth + 1)
        return [*path, ("<unequal-but-fields-match>", repr(oracle)[:120], repr(candidate)[:120])]
    return [*path, ("<value>", repr(oracle), repr(candidate))]


def _format_diff_path(steps: list) -> str:
    """Format a diff path as breadcrumbs ending with the differing
    oracle/candidate values."""
    if not steps:
        return "  (no diff)"
    breadcrumbs: list[str] = []
    terminal: tuple[str, str, str] | None = None
    for step in steps:
        if isinstance(step, tuple):
            terminal = step
        else:
            breadcrumbs.append(step)
    label = "root" + "".join(breadcrumbs)
    if terminal is None:
        return f"  {label}: (no terminal value)"
    field, o_repr, c_repr = terminal
    return f"  {label}{field}\n    oracle:    {o_repr[:200]}\n    candidate: {c_repr[:200]}"


# ---------------------------------------------------------------------------
# Divergence shape (a stable bucket key — used for shrinking + corpus dedup)
# ---------------------------------------------------------------------------
#
# Two divergences are "the same shape" if they reach the same terminal
# diff at the same root-type pair, OR they're the same kind of reject
# (matching error message).


@dataclasses.dataclass(frozen=True)
class DivergenceShape:
    """Structural-only divergence descriptor — designed so two examples
    of the same divergence (with different leaf values) compare equal.

    For ast_mismatch:
      - `kind` = "ast_mismatch"
      - `root_pair` = (oracle_root_type, candidate_root_type)
      - `terminal_kind` = the kind tag of the final diff step
        (`<type>` / `<value>` / `<keys>` / `<len>` /
        `<unequal-but-fields-match>` / `<depth-limit>`).
      - `terminal_types` = for `<type>` terminals only, the
        (oracle_type, candidate_type) pair that diverged. None for
        all other terminal kinds — those are inherently structural.

    For candidate_reject:
      - `kind` = "candidate_reject"
      - `reject_signature` = the normalised error message
    """

    kind: str
    root_pair: tuple[str, str] | None = None
    terminal_kind: str | None = None
    terminal_types: tuple[str, str] | None = None
    reject_signature: str | None = None


def _ast_mismatch_shape(root_pair: tuple[str, str], steps: list) -> DivergenceShape:
    """Build a structural `DivergenceShape` for an ast_mismatch from the
    root-type pair and the diff-path output. Accepts both tuple-form
    steps (in-memory) and list-form (after JSON round-trip). Leaf VALUES
    of `<value>` / `<keys>` / `<len>` are intentionally dropped — two
    divergences are "the same shape" if they reach the same kind of leaf
    at the same root, regardless of which specific value differed."""
    terminal: tuple[str, str, str] | None = None
    for s in reversed(steps):
        if isinstance(s, tuple) and len(s) == 3:
            terminal = s
            break
        if isinstance(s, list) and len(s) == 3 and all(isinstance(x, str) for x in s):
            terminal = (s[0], s[1], s[2])
            break
    if terminal is None:
        return DivergenceShape(kind="ast_mismatch", root_pair=root_pair)
    kind_tag = terminal[0]
    types = (terminal[1], terminal[2]) if kind_tag == "<type>" else None
    return DivergenceShape(
        kind="ast_mismatch",
        root_pair=root_pair,
        terminal_kind=kind_tag,
        terminal_types=types,
    )


# ---------------------------------------------------------------------------
# Error normalisation
# ---------------------------------------------------------------------------

_GOT_RE = re.compile(r"got\s+\S+", re.IGNORECASE)


def _normalize_error(msg: str) -> str:
    """Strip position-dependent suffixes so similar rejects bucket
    together — e.g. `expected ), got Keyword(Order)` and `expected ),
    got Number` collapse to `expected ), got <X>`."""
    return _GOT_RE.sub("got <X>", msg)[:120]


def _strip_locations() -> bool:
    """Whether to apply `clear_locations()` to parsed ASTs before the
    oracle-vs-candidate `==` check. Off by default — diagnostics include
    per-node `start` / `end` positions in the parity check now that the
    rust backend emits them with cpp-parity spans. Set `CLEAR_LOCATIONS=1`
    to revert to the structural-only comparison."""
    return os.environ.get("CLEAR_LOCATIONS", "").lower() in ("1", "true", "yes")


def _abort_on_shadow_mismatch(backend: str, exc: HogQLParserShadowMismatch) -> NoReturn:
    """Abort the whole diagnostic when a backend raises HogQLParserShadowMismatch.

    A `*_shadow` parser mode means `backend` is not a single pure parser: it ran the
    primary plus a shadow comparison and the two disagreed. An oracle/candidate that
    silently shadow-compares cannot be trusted because a genuine cpp-vs-rust ast_mismatch
    surfaces here as a backend crash instead of being categorized. Fail loud so the
    operator fixes the setup rather than recording masked results. Root cause is almost
    always `TEST=1`: parser.py routes the default 'cpp-json' backend to CPP_WITH_RUST_SHADOW
    whenever settings.TEST is truthy."""
    raise SystemExit(
        f"\nFATAL: backend {backend!r} raised HogQLParserShadowMismatch during the grind.\n"
        f"It is running a built-in shadow comparison, not a single pure parser, so the "
        f"diagnostic cannot trust it: real cpp-vs-rust AST divergences get masked as a crash "
        f"rather than surfacing as ast_mismatch.\n"
        f"Fix: re-run WITHOUT TEST=1. parser.py routes the default 'cpp-json' backend to "
        f"CPP_WITH_RUST_SHADOW when settings.TEST is set; with TEST unset the oracle is pure.\n"
        f"Shadow detail: {exc}"
    )


def _safe_parse(query: str, rule: str, backend: str) -> tuple[str, Any, str | None]:
    """Parse `query` for a diagnostic that must not abort mid-grind.
    Returns `(status, ast_or_none, detail)`:

    - `("ok", ast, None)` — parsed; AST keeps per-node `start` / `end`
      positions unless `CLEAR_LOCATIONS=1` strips them. Either way,
      callers can `==`-compare oracle vs candidate.
    - `("reject", None, signature)` — `BaseHogQLError`; a legitimate
      "not valid HogQL". `signature` is the normalised error message.
    - `("crash", None, signature)` — any other exception
      (`RecursionError`, a half-built backend's `RuntimeError`, …). The
      pytest PBT's own `_try_parse` lets these propagate so pytest
      records the failure; a CLI diagnostic instead buckets the crash
      as a finding and keeps going. `signature` is `<ExcType>: …`.

    `KeyboardInterrupt` / `SystemExit` are `BaseException`, not
    `Exception` — a manual Ctrl-C still propagates past this handler."""
    parser_fn = _PARSER_FOR_RULE[rule]
    try:
        node = parser_fn(query, backend=backend)
    except HogQLParserShadowMismatch as e:
        _abort_on_shadow_mismatch(backend, e)
    except BaseHogQLError as e:
        return "reject", None, _normalize_error(str(e))
    except Exception as e:
        return "crash", None, _normalize_error(f"{type(e).__name__}: {e}")
    return "ok", clear_locations(node) if _strip_locations() else node, None


# ---------------------------------------------------------------------------
# Backend probe + divergence classifier
# ---------------------------------------------------------------------------


def _probe_backend(rule: str, backend: str) -> str | None:
    """Sanity-probe a backend by parsing `"1"` directly through the
    parser entry point. Returns None on success, or a human-readable
    error message. Bypasses `_try_parse` deliberately — `_try_parse`
    swallows `BaseHogQLError` (legitimate rejections) AND would let an
    invalid backend name raising `KeyError` through silently."""
    probe_fn = _PARSER_FOR_RULE[rule]
    try:
        probe_fn("1", backend=backend)
    except BaseHogQLError:
        # Rejecting `"1"` would be surprising but isn't a backend
        # failure — `_try_parse` would also classify this as a reject.
        return None
    except Exception as e:
        return str(e)
    return None


def _shape_for(
    query: str,
    rule: str,
    oracle_backend: str,
    candidate_backend: str,
) -> DivergenceShape | None:
    """Determine the divergence shape of `query`, or None if there's no
    divergence to track. Returns None when the oracle crashes (nothing
    to compare against) and when the candidate crashes (a crash isn't a
    stable `DivergenceShape`, so the shrinker won't reduce toward one).

    Two-sided contract: when the oracle *rejects*, a candidate that
    *accepts* is the divergence (the candidate took an invalid query) —
    shape `candidate_accepts_oracle_reject`. Both rejecting is agreement,
    so there's nothing to shrink toward."""
    o_status, o_ast, _ = _safe_parse(query, rule, oracle_backend)
    if o_status == "crash":
        return None
    c_status, c_ast, c_detail = _safe_parse(query, rule, candidate_backend)
    if o_status == "reject":
        if c_status == "ok":
            return DivergenceShape(kind="candidate_accepts_oracle_reject")
        return None
    if c_status == "reject":
        return DivergenceShape(kind="candidate_reject", reject_signature=c_detail)
    if c_status == "crash":
        return None
    if o_ast == c_ast:
        return None
    return _ast_mismatch_shape((_node_type(o_ast), _node_type(c_ast)), _diff_path(o_ast, c_ast))


# ===========================================================================
# Corpus diagnostic machinery
# ===========================================================================
#
# Shared by `log_corpus_diagnostic.py` (HogQL queries from ClickHouse
# `system.query_log`) and `hog_corpus_diagnostic.py` (Hog programs from the
# Aurora Postgres `posthog_hogfunction` table). Metabase access, the
# paginated download, the oracle-vs-candidate parity grind, and the failure
# report are identical across both — only the SQL and its redaction dialect
# (ClickHouse `replaceRegexpAll` vs Postgres `regexp_replace`) differ, and
# those stay in the per-corpus scripts.

# Metabase's `/api/dataset` endpoint truncates every response to 2000 rows
# regardless of the SQL `LIMIT`; anything larger is fetched by paging.
MB_PAGE_SIZE = 2000


def hogli_bin(repo_root: Path) -> str:
    """Absolute path to `bin/hogli` — `$PATH` has it under flox for
    interactive shells but agent / CI shells often don't."""
    cand = repo_root / "bin" / "hogli"
    if not cand.is_file():
        raise RuntimeError(f"bin/hogli not found at {cand} — is the repo root correct?")
    return str(cand)


def repo_relative(path: Path, repo_root: Path) -> str:
    """Repo-rooted string when `path` is inside `repo_root`, else verbatim —
    so an out-of-worktree `--input` still prints cleanly."""
    if path.is_absolute() and path.is_relative_to(repo_root):
        return str(path.relative_to(repo_root))
    return str(path)


def discover_metabase_db(
    region: str,
    engine: str,
    repo_root: Path,
    *,
    prefer_name_substring: str | None = None,
) -> int:
    """Return a Metabase database id for the given `engine` (`clickhouse`
    / `postgres`), preferring one whose name contains `prefer_name_substring`
    (case-insensitive) when given, else the lowest id for determinism.
    Raises if `hogli metabase:databases` fails — usually a stale cookie
    (`hogli metabase:login` first)."""
    out = subprocess.check_output(
        [hogli_bin(repo_root), "metabase:databases", "--region", region, "--format", "json"],
        cwd=repo_root,
        text=True,
        timeout=60,  # don't hang forever on a stalled Metabase / auth wait
    )
    dbs = json.loads(out)
    # case-insensitive: Metabase has drifted casing on metadata fields.
    matching = [db for db in dbs if db.get("engine", "").lower() == engine.lower()]
    if not matching:
        raise RuntimeError(f"No {engine} databases listed for region={region!r}")
    if prefer_name_substring:
        sub = prefer_name_substring.lower()
        preferred = sorted(
            (db for db in matching if sub in db.get("name", "").lower()),
            key=lambda d: d["id"],
        )
        if preferred:
            chosen = preferred[0]
            print(f"  using {engine} db id={chosen['id']} name={chosen['name']!r}")
            return int(chosen["id"])
        print(f"  no {engine} DB name matched {prefer_name_substring!r}; falling back to lowest id")
    chosen = sorted(matching, key=lambda d: d["id"])[0]
    print(f"  using {engine} db id={chosen['id']} name={chosen['name']!r}")
    return int(chosen["id"])


def _fetch_metabase_page(region: str, database_id: int, sql: str, tmp_path: Path, repo_root: Path) -> dict:
    """Run one SQL query via `hogli metabase:query`, returning the parsed
    Metabase `/api/dataset` JSON. hogli writes to `tmp_path`."""
    subprocess.run(
        [
            hogli_bin(repo_root),
            "metabase:query",
            "--region",
            region,
            "--database-id",
            str(database_id),
            "--format",
            "json",
            "--save",
            str(tmp_path),
            # SQL goes over stdin; `--timeout` covers the slow scan.
            "--timeout",
            "300",
        ],
        input=sql,
        text=True,
        check=True,
        cwd=repo_root,
        timeout=360,  # process-level backstop above hogli's own `--timeout 300`
    )
    with open(tmp_path) as f:
        return json.load(f)


def download_corpus(
    region: str,
    database_id: int,
    dump_path: Path,
    sql_limit: int,
    build_sql: Callable[[int, int], str],
    repo_root: Path,
) -> None:
    """Fetch up to `sql_limit` corpus rows and write them to `dump_path`
    (Metabase `/api/dataset` JSON shape: `{"data": {"cols", "rows"}}`).

    `build_sql(limit, offset)` produces the corpus SQL for one page.
    Metabase caps responses at `MB_PAGE_SIZE`, so larger pulls are paged
    and concatenated. Written via a `.tmp` sibling + `os.replace` so an
    interrupted scan can't leave a half-written dump."""
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    cols: list | None = None
    all_rows: list = []
    offset = 0
    page_tmp = dump_path.with_suffix(dump_path.suffix + ".page.tmp")
    try:
        while len(all_rows) < sql_limit:
            page_limit = min(MB_PAGE_SIZE, sql_limit - len(all_rows))
            print(f"  downloading rows {offset:,}–{offset + page_limit:,} via `hogli metabase:query` …")
            body = _fetch_metabase_page(region, database_id, build_sql(page_limit, offset), page_tmp, repo_root)
            data = body.get("data") if isinstance(body, dict) else None
            if not data or "rows" not in data or "cols" not in data:
                status = body.get("status") if isinstance(body, dict) else "<unknown>"
                error = body.get("error") if isinstance(body, dict) else None
                raise RuntimeError(
                    f"Metabase page at offset {offset} isn't a success payload (status={status!r}, error={error!r})"
                )
            if cols is None:
                cols = data["cols"]
            rows = data["rows"]
            all_rows.extend(rows)
            if len(rows) < page_limit:
                break  # short page → corpus exhausted
            offset += page_limit
    finally:
        page_tmp.unlink(missing_ok=True)
    merged = {"data": {"cols": cols or [], "rows": all_rows}, "status": "completed", "row_count": len(all_rows)}
    tmp_path = dump_path.with_suffix(dump_path.suffix + ".tmp")
    try:
        with open(tmp_path, "w") as f:
            json.dump(merged, f)
        os.replace(tmp_path, dump_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    print(
        f"  saved {len(all_rows):,} rows ({dump_path.stat().st_size:,} bytes) to {repo_relative(dump_path, repo_root)}"
    )


def load_corpus_rows(path: Path, *, text_col: str, count_col: str | None = None) -> list[tuple[str, int]]:
    """Read a Metabase JSON dump into `(text, n_occurrences)` pairs,
    skipping rows whose `text_col` is empty/blank. Columns are resolved
    by name so the reader survives column-order changes in the SQL."""
    if not path.exists():
        raise FileNotFoundError(
            f"corpus dump not found at {path}\n"
            "  hint: drop --skip-download to fetch it from Metabase, or pass --input PATH"
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
    if text_col not in col_idx:
        raise RuntimeError(f"dump columns {list(col_idx)} don't include {text_col!r} — re-run without --skip-download")
    text_i = col_idx[text_col]
    count_i = col_idx.get(count_col) if count_col else None
    out: list[tuple[str, int]] = []
    for row in data["rows"]:
        text = row[text_i]
        if not isinstance(text, str) or not text.strip():
            continue
        n = 1
        if count_i is not None:
            try:
                n = int(row[count_i])
            except (TypeError, ValueError):
                n = 1
        out.append((text, n))
    return out


# ---------------------------------------------------------------------------
# Error bucketing — group same-cause rejects / crashes together
# ---------------------------------------------------------------------------

_AT_RE = re.compile(r"at\s+(line\s+\d+|offset\s+\d+|position\s+\d+|\d+:\d+)", re.IGNORECASE)


def bucket_error(msg: str) -> str:
    """Normalise a reject message so same-cause rejects bucket together —
    drops `got <X>` operands and `at <pos>` suffixes, clips to 160."""
    return _AT_RE.sub("at <pos>", _GOT_RE.sub("got <X>", msg)).strip()[:160]


def crash_signature(tb: str) -> str:
    """Bucket a crash by its traceback's last line (`ExcType: message`)."""
    lines = [ln for ln in tb.splitlines() if ln.strip()]
    return bucket_error(lines[-1]) if lines else "<empty traceback>"


def corpus_try_parse(query: str, rule: str, backend: str) -> tuple[str, Any, str | None]:
    """Parse `query` for the corpus grind. Returns `(status, ast, detail)`:
    `ok` (AST keeps positions by default; `CLEAR_LOCATIONS=1` to strip),
    `reject` (detail = the raw `BaseHogQLError` message), or `crash`
    (detail = full traceback). Ctrl-C still propagates (`BaseException`,
    not `Exception`)."""
    parser_fn = _PARSER_FOR_RULE[rule]
    try:
        node = parser_fn(query, backend=backend)
        return "ok", clear_locations(node) if _strip_locations() else node, None
    except HogQLParserShadowMismatch as e:
        _abort_on_shadow_mismatch(backend, e)
    except BaseHogQLError as e:
        return "reject", None, str(e)
    except Exception:
        return "crash", None, traceback.format_exc()


# ---------------------------------------------------------------------------
# Failure file
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Failure:
    """One failing-corpus-entry record for the failure file."""

    # "candidate_reject" | "candidate_crash" | "ast_mismatch" | "oracle_crash"
    kind: str
    query: str
    detail: str  # rejection message, crash traceback, or formatted diff path
    n_occurrences: int


def write_failures(path: Path, failures: list[Failure], repo_root: Path, *, title: str) -> None:
    """One block per failing entry, separated by a `-- =====` ruler,
    carrying the rejection / traceback / AST diff so a follow-up triage
    pass can bucket by root cause. Written via a `.tmp` sibling +
    `os.replace` so a crash mid-write can't leave a truncated file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    by_kind = Counter(fa.kind for fa in failures)
    breakdown = ", ".join(f"{n} {kind}" for kind, n in sorted(by_kind.items())) or "none"
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w") as f:
        f.write(f"-- {title} — {len(failures)} entries\n")
        f.write(f"-- ({breakdown})\n")
        f.write("-- Each block: occurrences count, failure kind + detail, then the entry.\n\n")
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
# Parity grind
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ParityResult:
    """Outcome of `run_corpus_parity`: tallies, per-failure records, and
    the bucket counters for the summary."""

    counts: Counter
    failures: list[Failure]
    oracle_reject_buckets: Counter
    reject_buckets: Counter
    crash_buckets: Counter
    mismatch_buckets: Counter
    interrupted: bool


def run_corpus_parity(
    rows: list[tuple[str, int]],
    *,
    rule: str,
    oracle: str,
    candidate: str,
    verbose: bool = False,
    noun: str = "query",
) -> ParityResult:
    """Parse every `(text, n_occurrences)` row with the oracle then the
    candidate and classify the outcome: pass / candidate_reject /
    candidate_crash / ast_mismatch, plus oracle_reject (skipped) and
    oracle_crash. A SIGINT flushes partial results — the loop checks an
    interrupt flag at each iteration boundary so an interrupted run still
    returns everything accumulated so far."""
    counts: Counter[str] = Counter()
    failures: list[Failure] = []
    oracle_reject_buckets: Counter[str] = Counter()
    reject_buckets: Counter[str] = Counter()
    crash_buckets: Counter[str] = Counter()
    mismatch_buckets: Counter[tuple[str, str]] = Counter()
    interrupted = False

    def _on_sigint(_signum: int, _frame: object) -> None:
        nonlocal interrupted
        interrupted = True

    prev_sigint = signal.signal(signal.SIGINT, _on_sigint)
    try:
        for i, (query, n_occ) in enumerate(rows):
            if interrupted:
                print(f"\nInterrupted at {i}/{len(rows)} — writing partial results…")
                break
            if (i + 1) % 50 == 0:
                sys.stderr.write(
                    f"\r  [{noun}] {i + 1}/{len(rows)} processed (pass={counts['pass']} "
                    f"reject={counts['candidate_reject']} mismatch={counts['ast_mismatch']} "
                    f"crash={counts['candidate_crash'] + counts['oracle_crash']} "
                    f"skip={counts['oracle_reject']})"
                )
                sys.stderr.flush()
            counts["total"] += 1
            o_status, o_ast, o_detail = corpus_try_parse(query, rule, oracle)
            if o_status == "reject":
                counts["oracle_reject"] += 1
                oracle_reject_buckets[bucket_error(o_detail or "")] += 1
                continue
            if o_status == "crash":
                counts["oracle_crash"] += 1
                crash_buckets[crash_signature(o_detail or "")] += 1
                failures.append(Failure("oracle_crash", query, o_detail or "<no traceback>", n_occ))
                continue
            c_status, c_ast, c_detail = corpus_try_parse(query, rule, candidate)
            if c_status == "reject":
                counts["candidate_reject"] += 1
                reject_buckets[bucket_error(c_detail or "")] += 1
                failures.append(Failure("candidate_reject", query, c_detail or "<no message>", n_occ))
                continue
            if c_status == "crash":
                counts["candidate_crash"] += 1
                crash_buckets[crash_signature(c_detail or "")] += 1
                failures.append(Failure("candidate_crash", query, c_detail or "<no traceback>", n_occ))
                continue
            if o_ast == c_ast:
                counts["pass"] += 1
                continue
            counts["ast_mismatch"] += 1
            bucket = (_node_type(o_ast), _node_type(c_ast))
            mismatch_buckets[bucket] += 1
            failures.append(Failure("ast_mismatch", query, _format_diff_path(_diff_path(o_ast, c_ast)), n_occ))
            if verbose:
                print(f"  MISMATCH (seen {n_occ}x): {bucket[0]} vs {bucket[1]}")
    finally:
        signal.signal(signal.SIGINT, prev_sigint)
        sys.stderr.write("\r" + " " * 110 + "\r")
    return ParityResult(
        counts=counts,
        failures=failures,
        oracle_reject_buckets=oracle_reject_buckets,
        reject_buckets=reject_buckets,
        crash_buckets=crash_buckets,
        mismatch_buckets=mismatch_buckets,
        interrupted=interrupted,
    )


def print_corpus_summary(result: ParityResult, *, oracle: str, candidate: str) -> None:
    """Print the `=== Summary ===` tally and the per-bucket breakdowns."""
    counts = result.counts
    print()
    print("=== Summary ===")
    for k in ("total", "pass", "candidate_reject", "candidate_crash", "ast_mismatch", "oracle_crash", "oracle_reject"):
        print(f"  {k:25s} {counts[k]}")

    def _dump(label: str, buckets: Counter, limit: int) -> None:
        if not buckets:
            return
        print()
        print(f"=== {label} ({sum(buckets.values())} total) ===")
        for sig, n in buckets.most_common(limit):
            shown = sig if isinstance(sig, str) else f"{sig[0]:25s} vs {sig[1]}"
            print(f"  {n:5d}  {shown}")
        if len(buckets) > limit:
            print(f"  … and {len(buckets) - limit} more buckets")

    _dump(f"Oracle ({oracle}) reject buckets", result.oracle_reject_buckets, 20)
    _dump(f"Candidate ({candidate}) reject buckets", result.reject_buckets, 30)
    _dump("Crash buckets (non-HogQL exceptions)", result.crash_buckets, 30)
    _dump("AST mismatch buckets", result.mismatch_buckets, 30)
