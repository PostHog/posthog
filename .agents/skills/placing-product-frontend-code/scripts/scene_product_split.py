#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Report where a product's frontend currently lives: ``products/<name>/frontend/``,
``frontend/src/scenes/<name>/``, or both.

Advisory only — nothing here fails a build. It answers "does this scene directory have a
product counterpart, and how far has the move gone", so a new file lands in the right tree.

Usage:
    python scene_product_split.py                # every scene dir with a product counterpart
    python scene_product_split.py data-warehouse # one directory
"""

from __future__ import annotations

import sys
import argparse
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCENES_ROOT = REPO_ROOT / "frontend/src/scenes"
PRODUCTS_ROOT = REPO_ROOT / "products"

SOURCE_SUFFIXES = (".ts", ".tsx")


@dataclass(frozen=True)
class SceneDir:
    name: str
    scene_files: int
    product: str | None
    product_files: int

    @property
    def status(self) -> str:
        if self.product is None:
            return "app-level"
        if self.product_files == 0:
            return "not started"
        return "past halfway" if self.product_files >= self.scene_files else "under way"

    @property
    def destination(self) -> str | None:
        return f"products/{self.product}/frontend/" if self.product else None


def count_sources(root: Path) -> int:
    """Hand-written .ts/.tsx under root. `generated/` trees are orval's output, not migration progress."""
    if not root.is_dir():
        return 0
    return sum(
        1
        for path in root.rglob("*")
        if path.suffix in SOURCE_SUFFIXES and path.is_file() and "generated" not in path.relative_to(root).parts
    )


def product_directories() -> dict[str, str]:
    """Normalized product name -> real directory name. scenes/ uses kebab-case, products/ snake_case."""
    if not PRODUCTS_ROOT.is_dir():
        return {}
    return {entry.name.replace("_", ""): entry.name for entry in sorted(PRODUCTS_ROOT.iterdir()) if entry.is_dir()}


def scan() -> dict[str, SceneDir]:
    if not SCENES_ROOT.is_dir():
        return {}
    products = product_directories()
    found: dict[str, SceneDir] = {}
    for entry in sorted(SCENES_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        scene_files = count_sources(entry)
        if scene_files == 0:
            continue
        product = products.get(entry.name.replace("-", "").replace("_", ""))
        found[entry.name] = SceneDir(
            name=entry.name,
            scene_files=scene_files,
            product=product,
            product_files=count_sources(PRODUCTS_ROOT / product / "frontend") if product else 0,
        )
    return found


def describe(d: SceneDir) -> str:
    if not d.product:
        return f"  {d.name}/  {d.scene_files} files in scenes/  —  app-level scene, no product counterpart"
    return f"  {d.name}/  {d.scene_files} in scenes/, {d.product_files} in {d.destination}  —  {d.status}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", help="A scene directory name, e.g. data-warehouse.")
    args = parser.parse_args()

    found = scan()

    if args.directory:
        d = found.get(args.directory)
        if not d:
            products = product_directories()
            product = products.get(args.directory.replace("-", "").replace("_", ""))
            if product:
                print(f"No frontend/src/scenes/{args.directory}/ — put the UI in products/{product}/frontend/.")
            else:
                print(f"No frontend/src/scenes/{args.directory}/ and no products/ counterpart.")
                print("New product-shaped UI: `bin/hogli product:bootstrap <name>`. See products/README.md.")
            return 0
        print(describe(d))
        if d.product:
            print(f"\n  New files belong in {d.destination}, not frontend/src/scenes/{d.name}/.")
        return 0

    owned = [d for d in found.values() if d.product]
    print(f"{len(found)} scene dirs; {len(owned)} have a product counterpart; ", end="")
    print(f"{sum(d.scene_files for d in owned)} files awaiting a move.\n")
    print("Scene dirs whose UI belongs under products/ (most migrated first):\n")
    for d in sorted(owned, key=lambda d: -d.product_files):
        print(describe(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
