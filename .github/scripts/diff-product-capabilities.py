#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""Report surfaces that regressed between two capability spec builds.

A surface flipping to `unavailable` usually means a real product regression — a deleted
mcp/tools.yaml, a removed onboarding flow — rather than an intended change. Nothing else
would notice, because the spec regenerates happily either way.

Advisory only: prints GitHub Actions warnings and always exits 0. Publishing a correct
spec must never be blocked by the contents of that spec.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

# `unknown` is not a regression: it means a derivation was deferred or a world opened,
# not that a product lost a capability.
REGRESSED_TO = "unavailable"
REGRESSED_FROM = {"available", "preview"}


def _load(path: Path) -> tuple[set[str], dict[tuple[str, str, str], str]]:
    """Returns (product names, verdicts).

    Product names are read from the product list rather than inferred from the verdict
    keys: a product carrying no surfaces contributes no keys, and inferring names from
    keys would make it invisible to the added/removed comparison.
    """
    spec = json.loads(path.read_text())
    products = spec.get("products", [])
    names = {product["product"] for product in products}
    verdicts = {
        (product["product"], group, key): fact["availability"]
        for product in products
        for group in ("surfaces", "data_sources")
        for key, fact in product.get(group, {}).items()
    }
    return names, verdicts


def main(previous_path: str, current_path: str) -> int:
    previous_names, previous = _load(Path(previous_path))
    current_names, current = _load(Path(current_path))

    regressions = sorted(
        (product, group, key, was)
        for (product, group, key), was in previous.items()
        if was in REGRESSED_FROM and current.get((product, group, key)) == REGRESSED_TO
    )

    for product, group, key, was in regressions:
        print(f"::warning::{product}: {group}.{key} went {was} -> {REGRESSED_TO}")

    added = sorted(current_names - previous_names)
    removed = sorted(previous_names - current_names)
    if added:
        print(f"New products: {', '.join(added)}")
    if removed:
        print(f"::warning::Products no longer in the spec: {', '.join(removed)}")
    if not regressions and not removed:
        print("No capability regressions.")

    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: diff-product-capabilities.py <previous.json> <current.json>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
