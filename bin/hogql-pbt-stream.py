# ruff: noqa: T201
"""Continuous differential PBT for the hogql parsers.

Generates examples via the grammar strategies (same source as the
pytest harness) and compares the two HogQL parser backends — Python
(parse-tree converter) and C++ (visitor in `hogql_parser`). Each new
divergence is appended as a JSONL line to ``pbt-divergences.jsonl``
in the repo root. Runs forever; the caller streams the log.

Designed for background execution while fixes land on the main
session — periodically clear the log and stop/restart the process
after a batch of fixes so the failure set reflects the new state.

Usage:

    python bin/hogql-pbt-stream.py [--rule expr|select|both]
                                    [--log PATH]
                                    [--limit N]
                                    [--shrink-tries N]
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import signal
import hashlib
import argparse
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Make Django settings happy before importing posthog.*
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
os.environ.setdefault("TEST", "1")
os.environ.setdefault("DEBUG", "1")

import django  # noqa: E402

django.setup()


from posthog.hogql.errors import BaseHogQLError  # noqa: E402
from posthog.hogql.parser import parse_expr, parse_select  # noqa: E402
from posthog.hogql.test._generated_grammar_strategies import expr_strategy, select_strategy  # noqa: E402
from posthog.hogql.test.test_parser_grammar_pbt import _CPP_KNOWN_BUG_PATTERNS, _apply_jiggle  # noqa: E402
from posthog.hogql.visitor import clear_locations  # noqa: E402

DEFAULT_LOG = REPO_ROOT / "pbt-divergences.jsonl"

# Backends under comparison. Keep aligned with the pytest harness in
# test_parser_grammar_pbt.py.
BACKEND_A = "python"
BACKEND_B = "cpp-json"


def try_parse(query: str, rule: str, backend: str) -> tuple[bool, Any, str]:
    """Return (accepted, ast, err_msg)."""
    fn = parse_expr if rule == "expr" else parse_select
    try:
        node = fn(query, backend=backend)  # type: ignore[arg-type]
        return True, clear_locations(node), ""
    except BaseHogQLError as e:
        return False, None, f"hogql:{e}"
    except Exception as e:  # noqa: BLE001
        return False, None, f"{type(e).__name__}:{e}"


def discard(query: str) -> bool:
    """Mirror the pytest harness's discard set so background runs don't
    redundantly surface already-known cpp bugs."""
    return any(p.search(query) for p in _CPP_KNOWN_BUG_PATTERNS)


def fingerprint(query: str) -> str:
    """Stable hash for dedup. Whitespace and case differences keep the
    fingerprint stable so cosmetic jiggle variants don't flood the log."""
    canon = re.sub(r"\s+", " ", query.strip()).lower()
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:12]


def shrink(
    query: str,
    rule: str,
    tries: int,
    seen_repros: set[str],
) -> str:
    """A very dumb shrinker: try deleting suffixes and balanced parens
    while preserving the divergence. Bounded by ``tries`` so it doesn't
    eat the whole budget per find."""

    def diverges(q: str) -> bool:
        if discard(q):
            return False
        return check_one(q, rule) is not None

    current = query
    for _ in range(tries):
        candidates: list[str] = []
        # Suffix deletions (in whitespace-aligned chunks).
        tokens = current.split(" ")
        if len(tokens) > 4:
            candidates.append(" ".join(tokens[:-1]))
            candidates.append(" ".join(tokens[:-2]))
            candidates.append(" ".join(tokens[: len(tokens) // 2]))
        # Prefix deletions.
        if len(tokens) > 4:
            candidates.append(" ".join(tokens[1:]))
            candidates.append(" ".join(tokens[2:]))
        # Drop a balanced `(...)` group.
        for m in re.finditer(r"\(", current):
            start = m.start()
            depth = 0
            for i in range(start, len(current)):
                if current[i] == "(":
                    depth += 1
                elif current[i] == ")":
                    depth -= 1
                    if depth == 0:
                        candidates.append(current[:start] + current[i + 1 :])
                        break
        progress = False
        for c in candidates:
            c = c.strip()
            if len(c) < 4 or c == current:
                continue
            if c in seen_repros:
                continue
            if diverges(c):
                seen_repros.add(c)
                current = c
                progress = True
                break
        if not progress:
            break
    return current


def check_one(query: str, rule: str) -> dict | None:
    """Return a divergence record or None.

    Bidirectional: one-sided acceptance or AST mismatch both count.
    """
    if discard(query):
        return None
    a_ok, a_ast, a_err = try_parse(query, rule, BACKEND_A)
    b_ok, b_ast, b_err = try_parse(query, rule, BACKEND_B)
    if not a_ok and not b_ok:
        return None  # both rejected — uninteresting
    if a_ok != b_ok:
        accepted, rejected, rejected_err = (BACKEND_A, BACKEND_B, b_err) if a_ok else (BACKEND_B, BACKEND_A, a_err)
        return {
            "kind": "one_sided_accept",
            "query": query,
            "accepted_by": accepted,
            "rejected_by": rejected,
            "rejected_err": rejected_err[:300],
        }
    if a_ast != b_ast:
        return {
            "kind": "ast_mismatch",
            "query": query,
            f"{BACKEND_A}_ast": repr(a_ast)[:1500],
            f"{BACKEND_B}_ast": repr(b_ast)[:1500],
        }
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rule", choices=("expr", "select", "both"), default="both")
    ap.add_argument("--log", default=str(DEFAULT_LOG))
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Stop after this many distinct divergences (0 = unlimited).",
    )
    ap.add_argument(
        "--shrink-tries",
        type=int,
        default=8,
        help="Shrinker iteration cap per find (0 disables shrinking).",
    )
    ap.add_argument("--jiggle", action="store_true", help="Also try jiggled variants.")
    args = ap.parse_args()

    log_path = Path(args.log)
    seen: set[str] = set()
    # Pre-seed from any existing log so a restart picks up where we left off.
    if log_path.exists():
        with log_path.open() as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    seen.add(fingerprint(rec["query"]))
                except Exception:  # noqa: BLE001
                    pass

    rules = ("expr", "select") if args.rule == "both" else (args.rule,)
    strategies = {
        "expr": expr_strategy(),
        "select": select_strategy(),
    }

    def _shutdown(*_a: Any) -> None:
        print(
            f"\n[pbt-stream] stopping. seen {len(seen)} distinct divergences",
            file=sys.stderr,
        )
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print(
        f"[pbt-stream] writing to {log_path} (existing entries: {len(seen)})",
        file=sys.stderr,
    )
    print(
        f"[pbt-stream] comparing {BACKEND_A!r} vs {BACKEND_B!r}",
        file=sys.stderr,
    )
    start = time.time()
    examples = 0
    found = 0
    last_progress = start

    while True:
        for rule in rules:
            strat = strategies[rule]
            if args.jiggle:
                strat = strat.flatmap(_apply_jiggle)
            try:
                query = strat.example()
            except Exception:  # noqa: BLE001
                continue
            examples += 1
            rec = check_one(query, rule)
            if rec is None:
                if time.time() - last_progress > 30:
                    rate = examples / max(1.0, time.time() - start)
                    print(
                        f"[pbt-stream] {examples} examples, {found} divergences, {rate:.0f}/s",
                        file=sys.stderr,
                    )
                    last_progress = time.time()
                continue
            fp = fingerprint(rec["query"])
            if fp in seen:
                continue
            # Shrink before logging so the log has minimal repros.
            if args.shrink_tries > 0:
                shrunk = shrink(rec["query"], rule, args.shrink_tries, seen)
                if shrunk != rec["query"]:
                    rec["query"] = shrunk
                    new_check = check_one(shrunk, rule)
                    if new_check is not None:
                        rec = new_check
                    fp = fingerprint(rec["query"])
                    if fp in seen:
                        continue
            seen.add(fp)
            rec["fingerprint"] = fp
            rec["rule"] = rule
            rec["found_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            with log_path.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            found += 1
            print(
                f"[pbt-stream] #{found} {rec['kind']} ({rule}, fp={fp}): {rec['query'][:120]}",
                file=sys.stderr,
            )
            if args.limit and found >= args.limit:
                print(
                    f"[pbt-stream] hit limit of {args.limit}, stopping",
                    file=sys.stderr,
                )
                return 0


if __name__ == "__main__":
    sys.exit(main())
