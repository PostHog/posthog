#!/usr/bin/env python3
"""Map posthog.schema types to the products that depend on them.

Parses every ``<products_root>/**/*.py`` with ``ast`` and prints a JSON object
of type name → sorted product list. Products whose usage can't be resolved to
concrete types (star import, dynamic access, parse failure) land under the
``"*"`` wildcard key, which the caller treats as affected by any schema change.
"""

from __future__ import annotations

import ast
import sys
import json
from collections import Counter, defaultdict
from pathlib import Path

WILDCARD = "*"
# schema_enums holds the enum classes split out of posthog.schema — same schema.json names,
# so its importers depend on schema changes exactly like posthog.schema importers do.
SCHEMA_MODULES = ("posthog.schema", "posthog.schema_enums")


def _product_name(rel_path: Path) -> str | None:
    # hyphenated to match @posthog/products-<name>
    parts = rel_path.parts
    if not parts:
        return None
    return parts[0].replace("_", "-")


class _SchemaUsageVisitor(ast.NodeVisitor):
    """Resolve posthog.schema type references within a single module."""

    def __init__(self) -> None:
        self.types: set[str] = set()
        self.module_aliases: set[str] = set()  # names bound to posthog.schema (e.g. `schema`, `ps`)
        self.posthog_pkg = False  # `import posthog[.schema]` → resolve `posthog.schema.Foo`
        self.star_import = False
        self._alias_uses: Counter[str] = Counter()  # every reference to an alias
        self._alias_attr_uses: Counter[str] = Counter()  # references of the form `alias.Type`
        self._dotted_uses = 0  # every `posthog.schema` expression
        self._dotted_attr_uses = 0  # those of the form `posthog.schema.Type`

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module in SCHEMA_MODULES:
            for alias in node.names:
                if alias.name == "*":
                    self.star_import = True
                else:
                    # schema.json keys are the original names, not local aliases
                    self.types.add(alias.name)
        elif node.module == "posthog":
            for alias in node.names:
                if alias.name in ("schema", "schema_enums"):
                    self.module_aliases.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name in SCHEMA_MODULES:
                if alias.asname:
                    self.module_aliases.add(alias.asname)
                else:
                    self.posthog_pkg = True
            elif alias.name == "posthog" and alias.asname is None:
                self.posthog_pkg = True
        self.generic_visit(node)

    def _is_dotted_module(self, node: ast.expr) -> bool:
        return (
            self.posthog_pkg
            and isinstance(node, ast.Attribute)
            and node.attr in ("schema", "schema_enums")
            and isinstance(node.value, ast.Name)
            and node.value.id == "posthog"
        )

    def visit_Attribute(self, node: ast.Attribute) -> None:
        value = node.value
        if self._is_dotted_module(node):
            self._dotted_uses += 1
        # posthog.schema.Foo / posthog.schema_enums.Foo
        if self._is_dotted_module(value):
            self.types.add(node.attr)
            self._dotted_attr_uses += 1
        # alias.Foo
        elif isinstance(value, ast.Name) and value.id in self.module_aliases:
            self.types.add(node.attr)
            self._alias_attr_uses[value.id] += 1
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in self.module_aliases:
            self._alias_uses[node.id] += 1
        self.generic_visit(node)

    @property
    def is_wildcard(self) -> bool:
        # opaque if a star import, or a module binding is ever used bare rather than as `module.Type`
        return (
            self.star_import
            or self._dotted_uses > self._dotted_attr_uses
            or any(self._alias_uses[a] > self._alias_attr_uses[a] for a in self.module_aliases)
        )


def tree_usage(tree: ast.AST) -> tuple[set[str], bool]:
    """The schema types one module names, and whether its use is opaque."""
    visitor = _SchemaUsageVisitor()
    visitor.visit(tree)
    return visitor.types, visitor.is_wildcard


def file_usage(source: str) -> tuple[set[str], bool]:
    """tree_usage for a module's source. Raises SyntaxError."""
    # every relevant form contains "schema", so skip the rest cheaply
    if "schema" not in source:
        return set(), False
    return tree_usage(ast.parse(source))


def scan(products_root: str) -> dict[str, list[str]]:
    root = Path(products_root)
    type_to_products: dict[str, set[str]] = defaultdict(set)
    for path in sorted(root.rglob("*.py")):
        product = _product_name(path.relative_to(root))
        if product is None:
            continue
        try:
            types, wildcard = file_usage(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            type_to_products[WILDCARD].add(product)
            continue
        for type_name in types:
            type_to_products[type_name].add(product)
        if wildcard:
            type_to_products[WILDCARD].add(product)
    return {key: sorted(products) for key, products in sorted(type_to_products.items())}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: schema_usage_scan.py <products_root>\n")
        return 2
    json.dump(scan(argv[1]), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
