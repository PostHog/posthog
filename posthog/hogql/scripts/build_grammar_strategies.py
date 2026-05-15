#!/usr/bin/env python3
"""Regenerate the HogQL grammar PBT strategies module.

Reads ``posthog/hogql/grammar/HogQLParser.g4`` and
``posthog/hogql/grammar/HogQLLexer.common.g4`` and emits
``posthog/hogql/test/_generated_grammar_strategies.py``.

Modes:

    python -m posthog.hogql.scripts.build_grammar_strategies
        Regenerate and write the file.

    python -m posthog.hogql.scripts.build_grammar_strategies --check
        Regenerate to memory and exit non-zero if the on-disk file
        differs. Use in CI to catch drift between the grammar and the
        checked-in generated strategies.

The codegen library is at ``posthog/hogql/scripts/grammar_codegen.py``.
"""
# ruff: noqa: T201

from __future__ import annotations

import sys
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from posthog.hogql.scripts.grammar_codegen import generate  # noqa: E402

PARSER_GRAMMAR = REPO_ROOT / "posthog" / "hogql" / "grammar" / "HogQLParser.g4"
LEXER_GRAMMAR = REPO_ROOT / "posthog" / "hogql" / "grammar" / "HogQLLexer.common.g4"
OUTPUT_PATH = REPO_ROOT / "posthog" / "hogql" / "test" / "_generated_grammar_strategies.py"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the on-disk generated file matches what we'd emit. Exit 1 on drift.",
    )
    args = parser.parse_args()

    source = generate(str(PARSER_GRAMMAR), str(LEXER_GRAMMAR))

    if args.check:
        if not OUTPUT_PATH.exists():
            print(f"FAIL: {OUTPUT_PATH} does not exist. Run without --check to regenerate.")
            return 1
        existing = OUTPUT_PATH.read_text()
        if existing != source:
            print(
                f"FAIL: {OUTPUT_PATH} is out of sync with the grammar.\n"
                f"Run `python -m posthog.hogql.scripts.build_grammar_strategies` to regenerate."
            )
            return 1
        print(f"OK: {OUTPUT_PATH} is in sync with the grammar.")
        return 0

    OUTPUT_PATH.write_text(source)
    print(f"Wrote {OUTPUT_PATH} ({len(source)} bytes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
