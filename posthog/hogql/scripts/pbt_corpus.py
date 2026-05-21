"""Regression corpus tool for parser-parity divergences.

Companion to `pbt_diagnostic.py`. Two subcommands:

  extract  Read a divergences JSONL (produced by
           `pbt_diagnostic.py --write-divergences`) and write a
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
    python posthog/hogql/scripts/pbt_diagnostic.py --n 5000 \\
        --shrink-failures --write-divergences /tmp/divergences.jsonl

    # 2. Extract a deduplicated regression corpus.
    python posthog/hogql/scripts/pbt_corpus.py extract \\
        --from /tmp/divergences.jsonl \\
        --to /tmp/pbt_regression_corpus.jsonl

    # 3. After making a fix, replay the corpus to see what changed.
    python posthog/hogql/scripts/pbt_corpus.py check \\
        --corpus /tmp/pbt_regression_corpus.jsonl
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

from posthog.hogql.scripts._diagnostic_common import (
    DivergenceShape,
    _ast_mismatch_shape,
    _probe_backend,
    _shape_for,
    corpus_try_parse,
)


def _shape_from_divergence(rec: dict) -> DivergenceShape:
    """Build the structural shape recorded in a divergences-JSONL row.
    Same canonical shape `_shape_for` produces, so two examples of the
    same divergence (with different leaf values) compare equal under
    this key."""
    if rec["kind"] == "ast_mismatch":
        return _ast_mismatch_shape(
            (rec.get("oracle_root", ""), rec.get("candidate_root", "")),
            rec.get("diff_path", []),
        )
    return DivergenceShape(kind="candidate_reject", reject_signature=rec.get("reject_signature"))


def _shape_from_corpus_entry(entry: dict) -> DivergenceShape:
    """Reconstruct the expected shape from a corpus-JSONL row produced
    by `cmd_extract`. Mirrors what `_shape_from_divergence` would
    produce on the original raw record."""
    if entry["kind"] == "ast_mismatch":
        types = None
        if "expected_terminal_oracle" in entry:
            types = (entry["expected_terminal_oracle"], entry["expected_terminal_candidate"])
        return DivergenceShape(
            kind="ast_mismatch",
            root_pair=(entry["expected_oracle_root"], entry["expected_candidate_root"]),
            terminal_kind=entry.get("expected_terminal_kind"),
            terminal_types=types,
        )
    return DivergenceShape(kind="candidate_reject", reject_signature=entry.get("expected_reject_signature"))


def cmd_extract(args: argparse.Namespace) -> int:
    # `DivergenceShape` is a frozen dataclass so it's hashable on its
    # own fields — use the shape directly as the dedup key.
    seen: dict[DivergenceShape, dict] = {}
    skipped_no_shrunk = 0
    with open(args.src) as f:
        for line in f:
            rec = json.loads(line)
            if not args.keep_unshrunken and "query_shrunk" not in rec:
                skipped_no_shrunk += 1
                continue
            shape = _shape_from_divergence(rec)
            if shape in seen:
                continue
            # Prefer the shrunken query if available.
            entry = {
                "kind": rec["kind"],
                "rule": rec["rule"],
                "oracle": rec["oracle"],
                "candidate": rec["candidate"],
                "query": rec.get("query_shrunk", rec["query"]),
            }
            if shape.kind == "ast_mismatch":
                entry["expected_oracle_root"] = shape.root_pair[0] if shape.root_pair else ""
                entry["expected_candidate_root"] = shape.root_pair[1] if shape.root_pair else ""
                if shape.terminal_kind:
                    entry["expected_terminal_kind"] = shape.terminal_kind
                if shape.terminal_types:
                    entry["expected_terminal_oracle"] = shape.terminal_types[0]
                    entry["expected_terminal_candidate"] = shape.terminal_types[1]
            else:
                entry["expected_reject_signature"] = shape.reject_signature
            seen[shape] = entry

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
    fixed / regressed / oracle-rejects. Exit 0 iff there are neither
    regressions nor oracle-reject entries (an oracle that now rejects
    a recorded query means the comparison baseline has shifted, so a
    bare "0 regressions" verdict can no longer be trusted)."""
    counts: Counter[str] = Counter()
    sample: dict[str, list[str]] = {"fixed": [], "regressed": [], "still_diverges": [], "oracle_rejects": []}
    # Sanity-probe each (oracle, candidate, rule) tuple we'll use the
    # first time we see it. `_shape_for` -> `_safe_parse` swallows the
    # `KeyError` raised by an invalid backend name silently, which
    # would classify every corpus entry as "fixed" with no error.
    # Probing lazily inside the loop catches both `--oracle` /
    # `--candidate` typos AND corpus files referring to backends that
    # were removed since the corpus was generated. The `rule` is part
    # of the key because a backend with partial coverage (e.g. expr
    # only, no select) needs to be caught for EACH rule the corpus
    # uses — otherwise the first entry's rule probes successfully and
    # the unprobed rule's entries all silently misclassify.
    probed: set[tuple[str, str, str]] = set()
    with open(args.corpus) as f:
        for line in f:
            entry = json.loads(line)
            oracle = args.oracle or entry["oracle"]
            candidate = args.candidate or entry["candidate"]
            rule = entry["rule"]
            if (oracle, candidate, rule) not in probed:
                for label, backend in (("oracle", oracle), ("candidate", candidate)):
                    err = _probe_backend(rule, backend)
                    if err is not None:
                        print(f"ERROR: {label} backend {backend!r} unavailable for rule {rule!r}: {err}")
                        return 2
                probed.add((oracle, candidate, rule))
            # `_shape_for` returns None for TWO distinct cases: oracle
            # and candidate agree (genuinely fixed), OR the oracle no
            # longer cleanly accepts the query. Every corpus entry was
            # recorded *because* the oracle accepted it, so an oracle
            # reject/crash is a behaviour change in the oracle itself —
            # classifying it as "fixed" would let a regressed oracle
            # masquerade as a clean run. Check the oracle independently
            # first and bucket those separately. (The startup probe
            # only checks the oracle is reachable via a trivial `"1"`
            # parse — it can't catch a per-query behaviour change.)
            o_status, _, _ = corpus_try_parse(entry["query"], rule, oracle)
            if o_status != "ok":
                counts["oracle_rejects"] += 1
                if len(sample["oracle_rejects"]) < args.max_samples:
                    sample["oracle_rejects"].append(entry["query"])
                continue
            shape = _shape_for(entry["query"], entry["rule"], oracle, candidate)
            if shape is None:
                counts["fixed"] += 1
                if len(sample["fixed"]) < args.max_samples:
                    sample["fixed"].append(entry["query"])
                continue
            expected = _shape_from_corpus_entry(entry)
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
    for label in ("fixed", "regressed", "still_diverges", "oracle_rejects"):
        if sample[label]:
            print()
            print(f"--- {label} (showing up to {args.max_samples}) ---")
            for q in sample[label]:
                print(f"  {q}")
    if counts["oracle_rejects"]:
        print(
            f"\nWARNING: the oracle now rejects {counts['oracle_rejects']} corpus "
            f"{'entry' if counts['oracle_rejects'] == 1 else 'entries'} it previously "
            f"accepted — the comparison baseline has shifted. Regenerate the corpus "
            f"against the current oracle before trusting the fixed/regressed counts."
        )
    return 0 if counts["regressed"] == 0 and counts["oracle_rejects"] == 0 else 1


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
