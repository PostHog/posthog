"""Regression corpus tool for parser-parity divergences.

Companion to `_pbt_diagnostic.py`. Two subcommands:

  extract  Read a divergences JSONL (produced by
           `_pbt_diagnostic.py --write-divergences`) and write a
           deduplicated corpus — one entry per
           (kind, oracle_root, candidate_root, terminal_diff_or_signature)
           bucket. The first occurrence of each bucket wins; we trust
           that the shrinker has already minimised it.

  check    Read a corpus and verify each entry still triggers its
           recorded divergence shape against the configured backends.
           Useful before/after a fix: any entry whose shape no longer
           matches has either been FIXED (good — remove from corpus)
           or REGRESSED into a different shape (bad — investigate).

Backend-agnostic: the corpus records the (oracle, candidate) pair the
divergence was found against. `check` re-runs against the same pair
unless overridden via `--oracle` / `--candidate`.

Typical workflow:

    # 1. Grind the PBT, persist divergences, shrink them.
    python posthog/hogql/test/_pbt_diagnostic.py --n 5000 \\
        --shrink-failures --write-divergences /tmp/divergences.jsonl

    # 2. Extract a deduplicated regression corpus.
    python posthog/hogql/test/_pbt_corpus.py extract \\
        --from /tmp/divergences.jsonl \\
        --to posthog/hogql/test/_pbt_regression_corpus.jsonl

    # 3. After making a fix, replay the corpus to see what changed.
    python posthog/hogql/test/_pbt_corpus.py check \\
        --corpus posthog/hogql/test/_pbt_regression_corpus.jsonl
"""

# ruff: noqa: T201 (CLI script — print is the report channel)
# ruff: noqa: E402 (django.setup() ordering)

from __future__ import annotations

import os
import sys
import json
import argparse
from collections import Counter

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.hogql.test._pbt_diagnostic import DivergenceShape, _shape_for, _shape_from_terminal, _terminal_of


def _bucket_key(rec: dict) -> tuple:
    """Stable bucket key for deduping divergences. We use the same
    structural shape that `_shape_for` / `DivergenceShape` produce, so
    two examples of the same divergence (with different leaf values)
    bucket together."""
    if rec["kind"] == "ast_mismatch":
        shape = _shape_from_terminal(
            (rec.get("oracle_root", ""), rec.get("candidate_root", "")),
            _terminal_of(rec.get("diff_path", [])),
        )
        return ("ast_mismatch", shape.root_pair, shape.terminal_kind, shape.terminal_types)
    if rec["kind"] == "candidate_reject":
        return ("candidate_reject", rec.get("reject_signature"))
    return ("unknown",)


def cmd_extract(args: argparse.Namespace) -> int:
    seen: dict[tuple, dict] = {}
    skipped_no_shrunk = 0
    with open(args.src) as f:
        for line in f:
            rec = json.loads(line)
            if not args.keep_unshrunken and "query_shrunk" not in rec:
                skipped_no_shrunk += 1
                continue
            key = _bucket_key(rec)
            if key in seen:
                continue
            # Prefer the shrunken query if available.
            entry = {
                "kind": rec["kind"],
                "rule": rec["rule"],
                "oracle": rec["oracle"],
                "candidate": rec["candidate"],
                "query": rec.get("query_shrunk", rec["query"]),
            }
            if rec["kind"] == "ast_mismatch":
                shape = _shape_from_terminal(
                    (rec["oracle_root"], rec["candidate_root"]),
                    _terminal_of(rec["diff_path"]),
                )
                entry["expected_oracle_root"] = shape.root_pair[0] if shape.root_pair else ""
                entry["expected_candidate_root"] = shape.root_pair[1] if shape.root_pair else ""
                if shape.terminal_kind:
                    entry["expected_terminal_kind"] = shape.terminal_kind
                if shape.terminal_types:
                    entry["expected_terminal_oracle"] = shape.terminal_types[0]
                    entry["expected_terminal_candidate"] = shape.terminal_types[1]
            elif rec["kind"] == "candidate_reject":
                entry["expected_reject_signature"] = rec["reject_signature"]
            seen[key] = entry

    with open(args.dst, "w") as f:
        for entry in seen.values():
            f.write(json.dumps(entry) + "\n")
    print(f"Wrote {len(seen)} deduplicated entries to {args.dst}")
    if skipped_no_shrunk:
        print(
            f"  ({skipped_no_shrunk} input records skipped because they have no "
            f"`query_shrunk` field — re-run the diagnostic with --shrink-failures, "
            f"or pass --keep-unshrunken to extract them anyway.)"
        )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Replay the corpus, classifying each entry as still-diverges /
    fixed / regressed. Exit 0 iff no regressions."""
    counts: Counter[str] = Counter()
    sample: dict[str, list[str]] = {"fixed": [], "regressed": [], "still_diverges": []}
    with open(args.corpus) as f:
        for line in f:
            entry = json.loads(line)
            oracle = args.oracle or entry["oracle"]
            candidate = args.candidate or entry["candidate"]
            shape = _shape_for(entry["query"], entry["rule"], oracle, candidate)
            if shape is None:
                counts["fixed"] += 1
                if len(sample["fixed"]) < args.max_samples:
                    sample["fixed"].append(entry["query"])
                continue
            # Reconstruct the expected structural shape from the
            # corpus entry. terminal_types is only set for `<type>`
            # terminals (cf. _shape_from_terminal); other terminal
            # kinds carry no per-instance state.
            if entry["kind"] == "ast_mismatch":
                expected = DivergenceShape(
                    kind="ast_mismatch",
                    root_pair=(
                        entry["expected_oracle_root"],
                        entry["expected_candidate_root"],
                    ),
                    terminal_kind=entry.get("expected_terminal_kind"),
                    terminal_types=(
                        (
                            entry["expected_terminal_oracle"],
                            entry["expected_terminal_candidate"],
                        )
                        if "expected_terminal_oracle" in entry
                        else None
                    ),
                )
            else:
                expected = DivergenceShape(
                    kind="candidate_reject",
                    reject_signature=entry.get("expected_reject_signature"),
                )
            if shape == expected:
                counts["still_diverges"] += 1
                if len(sample["still_diverges"]) < args.max_samples:
                    sample["still_diverges"].append(entry["query"])
            else:
                counts["regressed"] += 1
                if len(sample["regressed"]) < args.max_samples:
                    sample["regressed"].append(
                        f"{entry['query']!r}\n      expected: {expected}\n      got:      {shape}"
                    )

    print(f"=== Corpus check ({sum(counts.values())} entries) ===")
    for k, v in counts.most_common():
        print(f"  {k:20s} {v}")
    for label in ("fixed", "regressed", "still_diverges"):
        if sample[label]:
            print()
            print(f"--- {label} (showing up to {args.max_samples}) ---")
            for q in sample[label]:
                print(f"  {q}")
    return 0 if counts["regressed"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_extract = sub.add_parser("extract", help="Dedup divergences JSONL into a corpus")
    p_extract.add_argument("--from", dest="src", required=True, metavar="JSONL")
    p_extract.add_argument("--to", dest="dst", required=True, metavar="JSONL")
    p_extract.add_argument(
        "--keep-unshrunken",
        action="store_true",
        help="Include records that lack a `query_shrunk` field (default: skip them, since unshrunken queries make for bad regression tests)",
    )
    p_extract.set_defaults(func=cmd_extract)

    p_check = sub.add_parser("check", help="Replay a corpus and classify outcomes")
    p_check.add_argument("--corpus", required=True, metavar="JSONL")
    p_check.add_argument(
        "--oracle",
        default=None,
        help="Override the oracle backend (default: use what each entry recorded)",
    )
    p_check.add_argument(
        "--candidate",
        default=None,
        help="Override the candidate backend (default: use what each entry recorded)",
    )
    p_check.add_argument("--max-samples", type=int, default=5)
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
