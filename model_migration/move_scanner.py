#!/usr/bin/env python3
"""
Auto-discovers file structure and re-exports to generate moves.yml for import rewriting.

Usage:
    python model_migration/move_scanner.py --product data_warehouse --output model_migration/moves.yml
"""

import argparse
import ast
from pathlib import Path
from typing import Dict, List, Set
import yaml


def discover_files(source_dir: Path) -> List[Path]:
    """Recursively find all Python files in source directory."""
    py_files = []
    for file in source_dir.rglob("*.py"):
        if "__pycache__" not in file.parts:
            py_files.append(file)
    return sorted(py_files)


def parse_init_exports(init_file: Path, package_name: str) -> Dict[str, str]:
    """
    Parse __init__.py to discover re-exported symbols.

    Returns: {symbol_name: source_module_path}
    """
    exports = {}

    if not init_file.exists():
        return exports

    try:
        tree = ast.parse(init_file.read_text())
    except SyntaxError:
        return exports

    for node in ast.walk(tree):
        # Handle: from .submodule import Symbol
        if isinstance(node, ast.ImportFrom):
            if node.module is None and node.level > 0:
                # Relative import like: from . import submodule
                continue

            # Resolve relative imports
            if node.level > 0:
                # from .models.table import DataWarehouseTable
                # level=1 means one dot, level=2 means two dots
                parts = package_name.split(".")
                if len(parts) < node.level:
                    continue
                base_parts = parts[:len(parts) - node.level]
                if node.module:
                    source_module = ".".join(base_parts + [node.module])
                else:
                    source_module = ".".join(base_parts)
            else:
                # Absolute import
                source_module = node.module if node.module else package_name

            # Extract imported names
            for alias in node.names:
                if isinstance(alias, ast.alias):
                    # Symbol name (may have 'as' alias)
                    symbol = alias.asname if alias.asname else alias.name

                    # Special case: 'import *' - we can't track these
                    if alias.name == "*":
                        continue

                    # Map symbol to its source module
                    exports[alias.name] = source_module

        # Handle: Symbol = submodule.Symbol (assignment-based re-export)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value, ast.Attribute):
                    # Extract the full attribute path
                    attr_parts = []
                    current = node.value
                    while isinstance(current, ast.Attribute):
                        attr_parts.append(current.attr)
                        current = current.value
                    if isinstance(current, ast.Name):
                        attr_parts.append(current.value)

                    # Reconstruct module path
                    if len(attr_parts) >= 2:
                        symbol_name = attr_parts[0]
                        module_path = ".".join(reversed(attr_parts[1:]))
                        # Assume it's relative to current package
                        exports[target.id] = f"{package_name}.{module_path}"

    return exports


def discover_model_classes(py_file: Path) -> List[str]:
    """Extract class names from a Python file (useful for models)."""
    classes = []

    try:
        tree = ast.parse(py_file.read_text())
    except SyntaxError:
        return classes

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.append(node.name)

    return classes


def generate_moves_config(
    product: str,
    source_base: str,
    target_base: str,
    source_dir: Path,
    target_dir: Path,
) -> dict:
    """
    Generate moves.yml structure by scanning source directory.

    Args:
        product: Product name (e.g., "data_warehouse")
        source_base: Source package path (e.g., "posthog.warehouse")
        target_base: Target package path (e.g., "products.data_warehouse.backend")
        source_dir: Source directory path
        target_dir: Target directory path
    """
    # Discover all Python files
    py_files = discover_files(source_dir)

    # Build file moves mapping
    file_moves = []
    for py_file in py_files:
        rel_path = py_file.relative_to(source_dir)
        target_path = target_dir / rel_path

        file_moves.append({
            "from": str(py_file),
            "to": str(target_path),
        })

    # Build module moves mapping
    # Map each submodule from source to target
    module_moves = {}

    # Add top-level mapping
    module_moves[source_base] = target_base

    # Add subdirectory mappings
    for subdir in source_dir.rglob("*"):
        if subdir.is_dir() and "__pycache__" not in subdir.parts:
            rel_path = subdir.relative_to(source_dir)
            source_module = f"{source_base}.{str(rel_path).replace('/', '.')}"
            target_module = f"{target_base}.{str(rel_path).replace('/', '.')}"
            module_moves[source_module] = target_module

    # Discover symbol re-exports from __init__.py files
    symbol_remap = {}

    for init_file in source_dir.rglob("__init__.py"):
        # Determine the package name for this __init__.py
        if init_file.parent == source_dir:
            package_name = source_base
        else:
            rel_path = init_file.parent.relative_to(source_dir)
            package_name = f"{source_base}.{str(rel_path).replace('/', '.')}"

        # Parse exports
        exports = parse_init_exports(init_file, package_name)

        if exports:
            symbol_remap[package_name] = exports

    # Build the config structure
    config = {
        "product": product,
        "source": source_base,
        "target": target_base,
        "file_moves": file_moves,
        "module_moves": module_moves,
        "symbol_remap": symbol_remap,
    }

    return config


def main():
    parser = argparse.ArgumentParser(
        description="Auto-discover structure and generate moves.yml for migration"
    )
    parser.add_argument(
        "--product",
        required=True,
        help="Product name (e.g., data_warehouse)",
    )
    parser.add_argument(
        "--source",
        help="Source package path (e.g., posthog.warehouse). Default: posthog.{product}",
    )
    parser.add_argument(
        "--target",
        help="Target package path (e.g., products.data_warehouse.backend). Default: products.{product}.backend",
    )
    parser.add_argument(
        "--output",
        default="model_migration/moves.yml",
        help="Output file path (default: model_migration/moves.yml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print config to stdout instead of writing file",
    )

    args = parser.parse_args()

    # Determine source and target paths
    product = args.product
    source_package = args.source or f"posthog.{product.replace('_', 'warehouse' if 'warehouse' in product else product)}"

    # Special handling for data_warehouse which uses 'warehouse' in path
    if product == "data_warehouse":
        source_package = "posthog.warehouse"

    target_package = args.target or f"products.{product}.backend"

    # Convert package paths to directory paths
    source_dir = Path(source_package.replace(".", "/"))
    target_dir = Path(target_package.replace(".", "/"))

    if not source_dir.exists():
        print(f"Error: Source directory {source_dir} does not exist")
        return 1

    # Generate configuration
    config = generate_moves_config(
        product=product,
        source_base=source_package,
        target_base=target_package,
        source_dir=source_dir,
        target_dir=target_dir,
    )

    # Output
    yaml_output = yaml.dump(config, default_flow_style=False, sort_keys=False)

    if args.dry_run:
        print("Generated moves.yml:")
        print("=" * 80)
        print(yaml_output)
    else:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(yaml_output)
        print(f"✓ Generated {output_path}")
        print(f"  - {len(config['file_moves'])} file moves")
        print(f"  - {len(config['module_moves'])} module mappings")
        print(f"  - {len(config['symbol_remap'])} packages with re-exports")

    return 0


if __name__ == "__main__":
    exit(main())
