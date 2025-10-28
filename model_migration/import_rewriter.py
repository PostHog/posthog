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
# Export Index Builder
# --------------------------


class ExportCollector(cst.CSTVisitor):
    """
    Collect public exports from a Python module.

    Extracts:
    - __all__ if present (most authoritative)
    - Public classes, functions (not starting with _)
    - Re-exports like: from .other import Foo
    """

    def __init__(self):
        self.public_names = set()
        self.all_literal = None  # set or None
        self.re_exports = {}  # {name: source_module}

    def visit_Assign(self, node: cst.Assign) -> None:
        """Look for __all__ = ["A", "B"] assignments."""
        for target in node.targets:
            if isinstance(target.target, cst.Name) and target.target.value == "__all__":
                # Try to parse __all__ list
                if isinstance(node.value, cst.List):
                    all_names = []
                    for elem in node.value.elements:
                        if isinstance(elem.value, cst.SimpleString):
                            # Remove quotes
                            name = elem.value.value.strip("\"'")
                            all_names.append(name)
                    self.all_literal = set(all_names)

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        """Collect public class names."""
        name = node.name.value
        if not name.startswith("_"):
            self.public_names.add(name)

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        """Collect public function names."""
        name = node.name.value
        if not name.startswith("_"):
            self.public_names.add(name)

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        """
        Collect re-exports like: from .other import Foo

        Note: We track these but they're less authoritative than
        direct definitions or __all__.
        """
        # Only handle relative imports from sibling modules
        if node.relative and isinstance(node.names, Sequence):
            level = len(node.relative)
            module_str = dotted_name(node.module) if node.module else None

            # Only track direct re-exports (from .foo import Bar)
            if level == 1:  # same package
                for alias in node.names:
                    if isinstance(alias, cst.ImportAlias) and isinstance(alias.name, cst.Name):
                        imported_name = alias.asname.name.value if alias.asname else alias.name.value
                        source_mod = module_str if module_str else ""
                        self.re_exports[imported_name] = source_mod


def eliminate_star_imports(package_path: Path) -> bool:
    """
    Remove star imports from package __init__.py after Pass A completes.

    This is safe to run after --bypass-init-aggregation has redirected all
    imports to their source modules, making the star imports unused.

    Args:
        package_path: Path to package directory

    Returns:
        True if modifications were made
    """
    init_file = package_path / "__init__.py"
    if not init_file.exists():
        return False

    code = init_file.read_text()
    tree = cst.parse_module(code)

    # Remove star import statements
    class StarImportRemover(cst.CSTTransformer):
        def __init__(self):
            self.removed_count = 0

        def leave_SimpleStatementLine(
            self, original_node: cst.SimpleStatementLine, updated_node: cst.SimpleStatementLine
        ) -> cst.SimpleStatementLine | cst.RemovalSentinel:
            """Remove lines containing star imports."""
            if len(updated_node.body) == 1 and isinstance(updated_node.body[0], cst.ImportFrom):
                imp = updated_node.body[0]
                if isinstance(imp.names, cst.ImportStar):
                    self.removed_count += 1
                    return cst.RemovalSentinel.REMOVE
            return updated_node

    remover = StarImportRemover()
    new_tree = tree.visit(remover)

    if remover.removed_count > 0:
        init_file.write_text(new_tree.code)
        print(f"  ✓ Removed {remover.removed_count} star imports from {init_file}")
        return True

    return False


def build_export_index_for_package(package_path: Path, package_module: str) -> dict[str, str]:
    """
    Build symbol → source_module mapping for a package with star imports.

    Args:
        package_path: Path to package directory (e.g. products/data_warehouse/backend/models)
        package_module: Full module name (e.g. products.data_warehouse.backend.models)

    Returns:
        {symbol_name: full.module.path}

    Example:
        {
            "DataWarehouseTable": "products.data_warehouse.backend.models.table",
            "DataWarehouseCredential": "products.data_warehouse.backend.models.credential",
        }
    """
    init_file = package_path / "__init__.py"
    if not init_file.exists():
        return {}

    # Parse __init__.py to find star imports
    init_code = init_file.read_text()
    init_tree = cst.parse_module(init_code)

    # Find all star imports: from .foo import *
    star_imports = []
    for stmt in init_tree.body:
        if isinstance(stmt, cst.SimpleStatementLine) and len(stmt.body) == 1:
            if isinstance(stmt.body[0], cst.ImportFrom):
                imp = stmt.body[0]
                if isinstance(imp.names, cst.ImportStar):
                    # Get module name from relative import
                    if imp.relative:
                        level = len(imp.relative)
                        module_str = dotted_name(imp.module) if imp.module else None
                        if level == 1 and module_str:  # from .foo import *
                            star_imports.append(module_str)

    # Build export index
    export_index = {}
    conflicts = []

    for submodule_name in star_imports:
        submodule_file = package_path / f"{submodule_name}.py"
        if not submodule_file.exists():
            print(f"⚠️  Submodule not found: {submodule_file}")
            continue

        # Parse submodule and collect exports
        code = submodule_file.read_text()
        tree = cst.parse_module(code)
        collector = ExportCollector()
        # LibCST uses wrapper.visit() not tree.walk()
        wrapper = cst.metadata.MetadataWrapper(tree)
        tree.visit(collector)

        # Use __all__ if present, otherwise all public names
        if collector.all_literal:
            exports = collector.all_literal
        else:
            exports = collector.public_names

        # Map each export to its source module
        full_module_path = f"{package_module}.{submodule_name}"
        for name in exports:
            if name in export_index:
                # Conflict - same symbol exported from multiple modules
                conflicts.append((name, export_index[name], full_module_path))
            export_index[name] = full_module_path

    # Report conflicts
    if conflicts:
        print(f"\n⚠️  Symbol conflicts detected in {package_module}:")
        for name, mod1, mod2 in conflicts:
            print(f"   - {name}: {mod1} vs {mod2}")
        print("   Using last occurrence. Review manually if needed.\n")

    return export_index


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
            # Only convert to absolute if the module path changed (module was moved)
            if new_mod != abs_module:
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
        # Only convert to absolute if the module path changed (module was moved)
        if new_mod != abs_module:
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
    parser.add_argument(
        "--bypass-init-aggregation",
        nargs="+",
        metavar="PACKAGE",
        help="Bypass __init__.py aggregation for specified packages (e.g. products.data_warehouse.backend.models)",
    )
    parser.add_argument(
        "--eliminate-stars",
        action="store_true",
        help="Remove star imports from __init__.py after redirecting imports (requires --bypass-init-aggregation)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write changes to files (opposite of --dry-run)",
    )

    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Config file {config_path} not found", file=sys.stderr)
        return 1

    root = Path(args.root).resolve()

    # Load configuration
    module_moves, symbol_exports = load_moves_config(config_path)

    # Build export indexes for --bypass-init-aggregation packages
    if args.bypass_init_aggregation:
        print("Building export indexes for init aggregation bypass...")
        for package_module in args.bypass_init_aggregation:
            # Convert module path to file path
            package_path = root / Path(package_module.replace(".", "/"))
            if not package_path.exists():
                print(f"⚠️  Package not found: {package_path}")
                continue

            print(f"  Scanning {package_module}...")
            export_index = build_export_index_for_package(package_path, package_module)
            if export_index:
                symbol_exports[package_module] = export_index
                print(f"  ✓ Added {len(export_index)} exports from {package_module}")
        print()

    print(f"Loaded configuration from {config_path}")
    print(f"  - {len(module_moves)} module mappings")
    print(f"  - {len(symbol_exports)} packages with re-exports")
    print()

    # Determine if we're in write mode
    write_mode = args.write or not args.dry_run
    if args.dry_run:
        print("DRY RUN MODE - No files will be modified")
        write_mode = False
    if args.write:
        write_mode = True
    print()

    # Rewrite imports
    dry_run = not write_mode
    if args.file:
        # Single file mode
        file_path = Path(args.file).resolve()
        if not file_path.exists():
            print(f"Error: File {file_path} not found", file=sys.stderr)
            return 1

        modified = rewrite_imports_in_file(file_path, module_moves, symbol_exports, root, dry_run)
        print()
        print(f"Modified: {1 if modified else 0} file")
    else:
        # Directory tree mode
        modified_count = rewrite_imports_in_tree(root, module_moves, symbol_exports, dry_run)
        print()
        print(f"Modified: {modified_count} files")

    # Pass B: Eliminate star imports if requested
    if args.eliminate_stars and args.bypass_init_aggregation and write_mode:
        print("\nPass B: Eliminating star imports from __init__.py files...")
        for package_module in args.bypass_init_aggregation:
            package_path = root / Path(package_module.replace(".", "/"))
            if package_path.exists():
                print(f"  Processing {package_module}...")
                if eliminate_star_imports(package_path):
                    print(f"    Star imports removed")
                else:
                    print(f"    No star imports found")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
