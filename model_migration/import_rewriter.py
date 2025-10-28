#!/usr/bin/env python3
"""
LibCST-based import rewriter for model migrations.

Adapted from: model_migration/libcst.md

Usage:
    python model_migration/import_rewriter.py --config moves.yml --dry-run
    python model_migration/import_rewriter.py --config moves.yml --write
"""

import sys
import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

import yaml
import libcst as cst
from libcst import FlattenSentinel

# --------------------------
# Helpers
# --------------------------


def dotted_name(node: Optional[cst.BaseExpression]) -> Optional[str]:
    """Extract dotted module name from AST node."""
    if node is None:
        return None
    parts = []
    cur = node
    while isinstance(cur, cst.Attribute):
        parts.append(cur.attr.value)
        cur = cur.value
    if isinstance(cur, cst.Name):
        parts.append(cur.value)
    else:
        return None
    return ".".join(reversed(parts))


def build_abs_module(current_module: str, level: int, module: Optional[str]) -> Optional[str]:
    """
    Resolve a relative import like `from ..feature import alpha` into absolute path
    based on the current module path.
    """
    if level == 0:
        return module
    parts = current_module.split(".")
    if len(parts) < level:
        return None
    base = parts[: len(parts) - level]
    if module:
        base.append(module)
    return ".".join(base)


def update_module_path(path: str, module_moves: dict[str, str]) -> str:
    """
    If a module path (or any of its prefixes) is moved, rewrite it.
    E.g. posthog.warehouse.models.table -> products.data_warehouse.backend.models.table
    if posthog.warehouse moved.
    """
    segments = path.split(".")
    # Try from longest to shortest prefix
    for i in range(len(segments), 0, -1):
        prefix = ".".join(segments[:i])
        if prefix in module_moves:
            new_prefix = module_moves[prefix]
            return ".".join([new_prefix] + segments[i:])
    return path


# --------------------------
# Transformer
# --------------------------


class ImportRewriter(cst.CSTTransformer):
    def __init__(
        self,
        current_module: str,
        module_moves: dict[str, str],
        symbol_exports: dict[str, dict[str, str]],
    ):
        """
        Args:
            current_module: Fully qualified module name of file being transformed
            module_moves: {old_module_path: new_module_path}
            symbol_exports: {package: {symbol: source_module}}
        """
        self.current_module = current_module
        self.module_moves = module_moves
        self.symbol_exports = symbol_exports

    # import posthog.warehouse.models as x
    def leave_Import(self, original_node: cst.Import, updated_node: cst.Import) -> cst.Import:
        """Transform simple import statements."""
        if not isinstance(updated_node.names, cst.ImportStar):
            new_names = []
            for alias in updated_node.names:
                name_str = dotted_name(alias.name)
                if not name_str:
                    new_names.append(alias)
                    continue

                # Rewrite module path only (no symbol-level rewrite for plain Import)
                rewritten = update_module_path(name_str, self.module_moves)
                if rewritten != name_str:
                    new_alias = alias.with_changes(name=cst.parse_expression(rewritten))
                    new_names.append(new_alias)
                else:
                    new_names.append(alias)

            return updated_node.with_changes(names=new_names)
        return updated_node

    # from X import a, b as c
    def leave_SimpleStatementLine(
        self,
        original_node: cst.SimpleStatementLine,
        updated_node: cst.SimpleStatementLine,
    ) -> cst.SimpleStatementLine | FlattenSentinel[cst.SimpleStatementLine]:
        """
        Transform from...import statements.

        Uses SimpleStatementLine instead of leave_ImportFrom to properly handle
        multi-split imports (when symbols from one import need to be split across
        multiple import statements).
        """
        # Check if this line contains an ImportFrom
        if len(updated_node.body) != 1:
            return updated_node

        stmt = updated_node.body[0]
        if not isinstance(stmt, cst.ImportFrom):
            return updated_node

        # Extract module information
        module_str = dotted_name(stmt.module) if stmt.module else None
        level = len(stmt.relative) if stmt.relative else 0

        # Resolve to absolute module path
        abs_module = build_abs_module(self.current_module, level, module_str)
        if not abs_module:
            return updated_node

        # Handle ImportStar (from X import *)
        if isinstance(stmt.names, cst.ImportStar):
            # Rewrite module path but keep star import
            new_mod = update_module_path(abs_module, self.module_moves)
            if new_mod != abs_module or level > 0:
                new_stmt = stmt.with_changes(
                    module=cst.parse_expression(new_mod) if new_mod else None,
                    relative=[],
                )
                return updated_node.with_changes(body=[new_stmt])
            return updated_node

        # Handle named imports
        if not isinstance(stmt.names, Sequence):
            return updated_node

        import_aliases = list(stmt.names)

        # 1) Check if importing from top-level package with re-exports
        if abs_module in self.symbol_exports:
            # Group imports by their true source module
            regroup: dict[str, list[cst.ImportAlias]] = {}
            leftover: list[cst.ImportAlias] = []

            for alias in import_aliases:
                if not isinstance(alias, cst.ImportAlias):
                    leftover.append(alias)
                    continue

                name = alias.name.value if isinstance(alias.name, cst.Name) else None
                if not name:
                    leftover.append(alias)
                    continue

                # Check if this symbol is re-exported
                source_mod = self.symbol_exports[abs_module].get(name)
                if source_mod:
                    # Apply module moves to the source
                    target_mod = update_module_path(source_mod, self.module_moves)

                    # Create clean alias without trailing comma
                    new_alias = cst.ImportAlias(
                        name=alias.name,
                        asname=alias.asname if alias.asname else None,
                    )
                    regroup.setdefault(target_mod, []).append(new_alias)
                else:
                    # Symbol not found in re-exports, keep as-is
                    leftover.append(alias)

            # If we regrouped symbols, create multiple import statements
            if regroup:
                new_lines = []

                # Create import statement for each target module
                for target_mod, aliases in regroup.items():
                    new_import = cst.ImportFrom(
                        module=cst.parse_expression(target_mod),
                        names=aliases,
                    )
                    new_lines.append(cst.SimpleStatementLine(body=[new_import]))

                # If there are leftover imports, keep them with updated module path
                if leftover:
                    new_mod = update_module_path(abs_module, self.module_moves)
                    leftover_import = stmt.with_changes(
                        module=cst.parse_expression(new_mod) if new_mod else None,
                        relative=[],
                        names=leftover,
                    )
                    new_lines.insert(0, cst.SimpleStatementLine(body=[leftover_import]))

                # Return multiple lines using FlattenSentinel
                return FlattenSentinel(new_lines)

        # 2) Regular module path rewrite (no re-exports involved)
        new_mod = update_module_path(abs_module, self.module_moves)
        if new_mod != abs_module or level > 0:
            # Clean up aliases - create new ones without trailing commas
            clean_aliases = []
            for alias in import_aliases:
                if isinstance(alias, cst.ImportAlias):
                    clean_alias = cst.ImportAlias(
                        name=alias.name,
                        asname=alias.asname if alias.asname else None,
                    )
                    clean_aliases.append(clean_alias)
                else:
                    clean_aliases.append(alias)

            new_stmt = stmt.with_changes(
                module=cst.parse_expression(new_mod) if new_mod else None,
                relative=[],
                names=clean_aliases,
            )
            return updated_node.with_changes(body=[new_stmt])

        return updated_node


# --------------------------
# Driver
# --------------------------


def discover_current_module(file: Path, root: Path) -> str:
    """Determine the module path for a Python file relative to project root."""
    rel = file.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    return ".".join(parts)


def load_moves_config(config_path: Path) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Load moves.yml and extract module_moves and symbol_remap."""
    data = yaml.safe_load(config_path.read_text())
    module_moves = data.get("module_moves", {})
    symbol_remap = data.get("symbol_remap", {})
    return module_moves, symbol_remap


def rewrite_imports_in_file(
    file_path: Path,
    module_moves: dict[str, str],
    symbol_exports: dict[str, dict[str, str]],
    root: Path,
    dry_run: bool = False,
) -> bool:
    """
    Rewrite imports in a single file.

    Returns True if file was modified.
    """
    current_module = discover_current_module(file_path, root)

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = cst.parse_module(source)
    except Exception as e:
        print(f"⚠ Skipping {file_path}: {e}", file=sys.stderr)
        return False

    transformer = ImportRewriter(
        current_module=current_module,
        module_moves=module_moves,
        symbol_exports=symbol_exports,
    )

    new_tree = tree.visit(transformer)
    new_code = new_tree.code

    if new_code != source:
        if not dry_run:
            file_path.write_text(new_code, encoding="utf-8")
            print(f"✓ Updated {file_path}")
        else:
            print(f"  Would update {file_path}")
        return True
    return False


def rewrite_imports_in_tree(
    root: Path,
    module_moves: dict[str, str],
    symbol_exports: dict[str, dict[str, str]],
    dry_run: bool = False,
    exclude_patterns: list[str] = None,
) -> int:
    """
    Rewrite imports in all Python files in directory tree.

    Returns number of files modified.
    """
    if exclude_patterns is None:
        exclude_patterns = ["site-packages", ".venv", "venv", "__pycache__", "node_modules"]

    py_files = []
    for py_file in root.rglob("*.py"):
        # Skip excluded patterns
        if any(pattern in py_file.parts for pattern in exclude_patterns):
            continue
        py_files.append(py_file)

    modified_count = 0
    for py_file in sorted(py_files):
        if rewrite_imports_in_file(py_file, module_moves, symbol_exports, root, dry_run):
            modified_count += 1

    return modified_count


def main():
    parser = argparse.ArgumentParser(description="Rewrite imports based on moves.yml configuration")
    parser.add_argument(
        "--config",
        default="model_migration/moves.yml",
        help="Path to moves.yml configuration file",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Project root directory (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying files",
    )
    parser.add_argument(
        "--file",
        help="Rewrite imports in a single file only",
    )

    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Config file {config_path} not found", file=sys.stderr)
        return 1

    root = Path(args.root).resolve()

    # Load configuration
    module_moves, symbol_exports = load_moves_config(config_path)

    print(f"Loaded configuration from {config_path}")
    print(f"  - {len(module_moves)} module mappings")
    print(f"  - {len(symbol_exports)} packages with re-exports")
    print()

    if args.dry_run:
        print("DRY RUN MODE - No files will be modified")
        print()

    # Rewrite imports
    if args.file:
        # Single file mode
        file_path = Path(args.file).resolve()
        if not file_path.exists():
            print(f"Error: File {file_path} not found", file=sys.stderr)
            return 1

        modified = rewrite_imports_in_file(file_path, module_moves, symbol_exports, root, args.dry_run)
        print()
        print(f"Modified: {1 if modified else 0} file")
    else:
        # Directory tree mode
        modified_count = rewrite_imports_in_tree(root, module_moves, symbol_exports, args.dry_run)
        print()
        print(f"Modified: {modified_count} files")

    return 0


if __name__ == "__main__":
    sys.exit(main())
