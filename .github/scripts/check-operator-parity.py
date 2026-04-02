#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
CI script to verify PropertyOperator (Python/TypeScript) and OperatorType (Rust)
enum variants stay in sync across languages.

When a new property filter operator is added to the TypeScript/Python schema,
it must also be added to the Rust feature flags evaluator (or explicitly
allowlisted here). Without this check, missing operators cause silent runtime
failures — e.g. serde deserialization errors in the Rust flag evaluator.

Usage:
    python .github/scripts/check-operator-parity.py

Exit codes:
    0 - All operators accounted for
    1 - Unexpected parity gap found (ERROR)
"""

import re
import sys
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

SCHEMA_JSON_PATH = REPO_ROOT / "frontend" / "src" / "queries" / "schema.json"
RUST_OPERATOR_PATH = REPO_ROOT / "rust" / "feature-flags" / "src" / "properties" / "property_models.rs"

# Operators intentionally present in Python/TypeScript but not in Rust.
# The Rust feature flag evaluator doesn't need these operators.
PYTHON_ONLY_ALLOWLIST: dict[str, str] = {
    "between": "Range comparison, only used in HogQL insights queries",
    "not_between": "Range comparison, only used in HogQL insights queries",
    "min": "Alias for gte, only used in HogQL insights queries",
    "max": "Alias for lte, only used in HogQL insights queries",
    "is_cleaned_path_exact": "Path normalization, only used in HogQL path analysis",
}

# Operators intentionally present in Rust but not in Python/TypeScript.
# This should normally be empty — Rust consumes the Python-defined schema.
RUST_ONLY_ALLOWLIST: dict[str, str] = {}


def pascal_to_snake(name: str) -> str:
    """Convert PascalCase to snake_case, matching serde's rename_all = "snake_case".

    Assumes no consecutive-uppercase acronyms (e.g. "URL" or "HTTP") — all current
    OperatorType variants use single-capital word boundaries like IsNotSet, SemverGt.
    """
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return s.lower()


def get_python_operators() -> set[str]:
    """Parse PropertyOperator values from the JSON schema (source of truth)."""
    with open(SCHEMA_JSON_PATH) as f:
        schema = json.load(f)

    operator_def = schema.get("definitions", {}).get("PropertyOperator", {})
    values = operator_def.get("enum", [])

    if not values:
        print(f"ERROR: Could not find PropertyOperator enum in {SCHEMA_JSON_PATH}")
        sys.exit(1)

    return set(values)


MIN_EXPECTED_RUST_VARIANTS = 20


def get_rust_operators() -> set[str]:
    """Parse OperatorType variants from the Rust source file."""
    content = RUST_OPERATOR_PATH.read_text()

    # Find the OperatorType enum block
    enum_match = re.search(r"pub\s+enum\s+OperatorType\s*\{([^}]+)\}", content, re.DOTALL)
    if not enum_match:
        print(f"ERROR: Could not find OperatorType enum in {RUST_OPERATOR_PATH}")
        sys.exit(1)

    enum_body = enum_match.group(1)

    # Strip lines that are comments or attributes so they don't interfere
    # with variant extraction (e.g. /// doc comments, #[serde(...)] attributes)
    cleaned_lines = []
    for line in enum_body.splitlines():
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#["):
            continue
        cleaned_lines.append(line)
    cleaned_body = "\n".join(cleaned_lines)

    # Extract variant names (PascalCase identifiers on their own lines)
    variants = re.findall(r"^\s*(\w+)\s*,?\s*$", cleaned_body, re.MULTILINE)
    if not variants:
        print("ERROR: Could not parse variants from OperatorType enum")
        sys.exit(1)

    if len(variants) < MIN_EXPECTED_RUST_VARIANTS:
        print(f"ERROR: Only parsed {len(variants)} Rust variants (expected >= {MIN_EXPECTED_RUST_VARIANTS}).")
        print("The enum parser may be broken — check for unexpected formatting in OperatorType.")
        sys.exit(1)

    return {pascal_to_snake(v) for v in variants}


def main() -> int:
    python_ops = get_python_operators()
    rust_ops = get_rust_operators()

    has_errors = False
    has_warnings = False

    # Check for operators in Python but not in Rust
    python_only = python_ops - rust_ops
    unexpected_python_only = python_only - set(PYTHON_ONLY_ALLOWLIST.keys())
    expected_python_only = python_only & set(PYTHON_ONLY_ALLOWLIST.keys())

    # Check for operators in Rust but not in Python
    rust_only = rust_ops - python_ops
    unexpected_rust_only = rust_only - set(RUST_ONLY_ALLOWLIST.keys())
    expected_rust_only = rust_only & set(RUST_ONLY_ALLOWLIST.keys())

    # Check for stale allowlist entries
    stale_python_allowlist = set(PYTHON_ONLY_ALLOWLIST.keys()) - python_only
    stale_rust_allowlist = set(RUST_ONLY_ALLOWLIST.keys()) - rust_only

    print("=" * 60)
    print("Property Operator Parity Check")
    print("=" * 60)
    print(f"\n  Python/TypeScript operators (schema.json): {len(python_ops)}")
    print(f"  Rust operators (property_models.rs):        {len(rust_ops)}")
    print(f"  Python-only allowlist:                      {len(PYTHON_ONLY_ALLOWLIST)}")
    print(f"  Rust-only allowlist:                        {len(RUST_ONLY_ALLOWLIST)}")

    if unexpected_python_only:
        has_errors = True
        print(f"\n  ERROR: Operators in Python but not in Rust (and not in allowlist):")
        for op in sorted(unexpected_python_only):
            print(f"     - {op}")

    if unexpected_rust_only:
        has_errors = True
        print(f"\n  ERROR: Operators in Rust but not in Python (and not in allowlist):")
        for op in sorted(unexpected_rust_only):
            print(f"     - {op}")

    if expected_python_only:
        print(f"\n  Allowlisted Python-only operators:")
        for op in sorted(expected_python_only):
            print(f"     - {op}: {PYTHON_ONLY_ALLOWLIST[op]}")

    if expected_rust_only:
        print(f"\n  Allowlisted Rust-only operators:")
        for op in sorted(expected_rust_only):
            print(f"     - {op}: {RUST_ONLY_ALLOWLIST[op]}")

    if stale_python_allowlist:
        has_warnings = True
        print(f"\n  WARNING: Stale entries in PYTHON_ONLY_ALLOWLIST (operator no longer Python-only):")
        for op in sorted(stale_python_allowlist):
            print(f"     - {op}")

    if stale_rust_allowlist:
        has_warnings = True
        print(f"\n  WARNING: Stale entries in RUST_ONLY_ALLOWLIST (operator no longer Rust-only):")
        for op in sorted(stale_rust_allowlist):
            print(f"     - {op}")

    if (
        not unexpected_python_only
        and not unexpected_rust_only
        and not stale_python_allowlist
        and not stale_rust_allowlist
    ):
        print("\n  All gaps accounted for")

    print("\n" + "=" * 60)

    if has_errors:
        print("\nFAILED: Unexpected operator parity gap found.")
        print("\nTo fix, either:")
        print("  1. Add the missing operator to the other language's enum:")
        print(f"     - Rust: {RUST_OPERATOR_PATH.relative_to(REPO_ROOT)}")
        print(f"     - Python/TS: frontend/src/types.ts (then run: hogli build:schema)")
        print("  2. Or add it to the appropriate allowlist in this script")
        print(f"     ({Path(__file__).relative_to(REPO_ROOT)})")
        print("     with a reason explaining why the gap is intentional.")
        return 1

    if has_warnings:
        print("\nPASSED with warnings: Some allowlist entries may be stale.")

    print("\nAll operators are in sync across languages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
