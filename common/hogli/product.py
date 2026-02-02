"""Product scaffolding and linting commands."""

from __future__ import annotations

from pathlib import Path

import yaml
import click
from hogli.core.cli import cli

STRUCTURE_FILE = Path(__file__).parent / "product_structure.yaml"
PRODUCTS_DIR = Path(__file__).parent.parent.parent / "products"
PRODUCTS_BUILD_FILE = PRODUCTS_DIR / "BUILD.bazel"


def load_structure() -> dict:
    """Load the canonical product structure from YAML."""
    return yaml.safe_load(STRUCTURE_FILE.read_text())


def _flatten_structure(files: dict, prefix: str = "", result: dict | None = None) -> dict[str, dict]:
    """
    Flatten nested structure into flat paths.
    e.g., {"api/": {"api.py": {...}}} -> {"api/api.py": {...}}
    """
    if result is None:
        result = {}

    for name, config in files.items():
        if name.endswith("/"):
            # Directory - recurse into children
            _flatten_structure(config, prefix + name, result)
        else:
            path = prefix + name
            result[path] = config if isinstance(config, dict) else {}

    return result


def _render_template(template: str, product_name: str) -> str:
    """Render template with product name substitutions."""
    # Convert snake_case to PascalCase for class names
    pascal_name = "".join(word.capitalize() for word in product_name.split("_"))
    return template.format(product=product_name, Product=pascal_name)


def _add_to_integration_tests_group(product_name: str, dry_run: bool) -> bool:
    """Add product to the integration_tests package_group in products/BUILD.bazel."""
    if not PRODUCTS_BUILD_FILE.exists():
        return False

    content = PRODUCTS_BUILD_FILE.read_text()
    package_entry = f'"//products/{product_name}/backend/tests"'

    # Check if already present
    if package_entry in content:
        return False

    # Find the packages list and add the new entry
    # Look for pattern: packages = [\n        "//products/...
    import re

    pattern = r'(package_group\(\s*name\s*=\s*"integration_tests",\s*packages\s*=\s*\[)([^\]]*?)(\s*\],)'

    def add_package(match: re.Match) -> str:
        prefix = match.group(1)
        existing = match.group(2)
        suffix = match.group(3)

        # Add new entry before the closing bracket
        if existing.strip():
            new_packages = existing.rstrip() + ",\n        " + package_entry
        else:
            new_packages = "\n        " + package_entry + "\n    "

        return prefix + new_packages + suffix

    new_content = re.sub(pattern, add_package, content, flags=re.DOTALL)

    if new_content == content:
        return False

    if not dry_run:
        PRODUCTS_BUILD_FILE.write_text(new_content)

    return True


def _add_to_isolated_products(product_name: str, dry_run: bool) -> bool:
    """Add product to ISOLATED_PRODUCTS list in products/BUILD.bazel.

    This excludes the product from the legacy_product_srcs filegroup,
    ensuring only the product's own Bazel tests run when its code changes.
    """
    if not PRODUCTS_BUILD_FILE.exists():
        return False

    content = PRODUCTS_BUILD_FILE.read_text()
    entry = f'"{product_name}"'

    # Check if already present
    if entry in content:
        return False

    # Find ISOLATED_PRODUCTS list and add the new entry (sorted)
    import re

    pattern = r"(ISOLATED_PRODUCTS\s*=\s*\[)([^\]]*?)(\])"

    def add_product(match: re.Match) -> str:
        prefix = match.group(1)
        existing = match.group(2)
        suffix = match.group(3)

        # Parse existing entries
        existing_products = re.findall(r'"([^"]+)"', existing)
        existing_products.append(product_name)
        existing_products.sort()

        # Format as list
        formatted = "\n    " + ",\n    ".join(f'"{p}"' for p in existing_products) + ",\n"

        return prefix + formatted + suffix

    new_content = re.sub(pattern, add_product, content, flags=re.DOTALL)

    if new_content == content:
        return False

    if not dry_run:
        PRODUCTS_BUILD_FILE.write_text(new_content)

    return True


def bootstrap_product(name: str, dry_run: bool, force: bool) -> None:
    """Create a new product with the canonical structure."""
    product_dir = PRODUCTS_DIR / name

    if product_dir.exists() and not force:
        raise click.ClickException(f"Product '{name}' already exists at {product_dir}. Use --force to overwrite.")

    structure = load_structure()
    created = []
    skipped = []

    # Root files
    root_files = _flatten_structure(structure.get("root_files", {}))
    for path, config in root_files.items():
        file_path = product_dir / path
        template = config.get("template", "")

        if dry_run:
            if file_path.exists() and not force:
                skipped.append(path)
            else:
                created.append(path)
            continue

        file_path.parent.mkdir(parents=True, exist_ok=True)
        if file_path.exists() and not force:
            skipped.append(path)
            continue

        content = _render_template(template, name)
        file_path.write_text(content)
        created.append(path)

    # Backend files
    backend_files = _flatten_structure(structure.get("backend_files", {}))
    for path, config in backend_files.items():
        file_path = product_dir / "backend" / path
        template = config.get("template", "")

        if dry_run:
            if file_path.exists() and not force:
                skipped.append(f"backend/{path}")
            else:
                created.append(f"backend/{path}")
            continue

        file_path.parent.mkdir(parents=True, exist_ok=True)
        if file_path.exists() and not force:
            skipped.append(f"backend/{path}")
            continue

        content = _render_template(template, name)
        file_path.write_text(content)
        created.append(f"backend/{path}")

    # Frontend folders
    frontend_files = structure.get("frontend_files", {})
    for folder_name in frontend_files.keys():
        folder_path = product_dir / "frontend" / folder_name.rstrip("/")
        if dry_run:
            created.append(f"frontend/{folder_name}")
        else:
            folder_path.mkdir(parents=True, exist_ok=True)
            created.append(f"frontend/{folder_name}")

    # Add to integration_tests package_group
    added_to_group = _add_to_integration_tests_group(name, dry_run)

    # Add to ISOLATED_PRODUCTS list (excludes from legacy blob)
    added_to_isolated = _add_to_isolated_products(name, dry_run)

    # Output results
    if dry_run:
        click.echo(f"Would create product '{name}' at {product_dir}")
    else:
        click.echo(f"Created product '{name}' at {product_dir}")

    if created:
        click.echo(f"\n  Created {len(created)} files/folders:")
        for path in created:
            click.echo(f"    {path}")

    if skipped:
        click.echo(f"\n  Skipped {len(skipped)} existing files:")
        for path in skipped:
            click.echo(f"    {path}")

    if added_to_group:
        if dry_run:
            click.echo("\n  Would add to products/BUILD.bazel integration_tests group")
        else:
            click.echo("\n  Added to products/BUILD.bazel integration_tests group")

    if added_to_isolated:
        if dry_run:
            click.echo("\n  Would add to ISOLATED_PRODUCTS in products/BUILD.bazel")
        else:
            click.echo("\n  Added to ISOLATED_PRODUCTS in products/BUILD.bazel")


def _check_file_exists(backend_dir: Path, path: str) -> bool:
    """Check if a file or its folder equivalent exists."""
    file_path = backend_dir / path
    if file_path.exists():
        return True
    if path.endswith(".py"):
        folder_path = backend_dir / path.replace(".py", "")
        if folder_path.exists() and folder_path.is_dir():
            return True
    return False


def lint_product(name: str, verbose: bool = True) -> list[str]:
    """
    Check for known files in wrong places.
    Returns list of issues found.
    """
    product_dir = PRODUCTS_DIR / name
    backend_dir = product_dir / "backend"

    if not product_dir.exists():
        raise click.ClickException(f"Product '{name}' not found at {product_dir}")

    structure = load_structure()

    issues = []

    # First, check if this is an isolated product (has dtos.py)
    dtos_file = backend_dir / "api" / "dtos.py"
    dtos_folder = backend_dir / "api" / "dtos"
    is_isolated = dtos_file.exists() or dtos_folder.exists()
    required_key = "required" if is_isolated else "required_lenient"

    if verbose:
        click.echo("  Checking for isolated architecture...")
        if is_isolated:
            click.echo("    ✓ Has backend/api/dtos.py - running strict checks")
        else:
            click.echo("    ○ No backend/api/dtos.py - legacy product, showing progress toward isolation")

    # Check for root files (manifest.tsx, package.json, tsconfig.json)
    if verbose:
        click.echo("  Checking for root files...")
    root_files = structure.get("root_files", {})
    missing_root = []
    for filename, config in root_files.items():
        if config.get(required_key, False):
            file_path = product_dir / filename
            if not file_path.exists():
                missing_root.append(filename)

    if verbose:
        if missing_root:
            click.echo(f"    ✗ Missing {len(missing_root)} required file(s): {', '.join(missing_root)}")
        else:
            click.echo("    ✓ All required root files present")

    for f in missing_root:
        issues.append(f"Missing required root file: {f}")

    # Check for misplaced files in backend
    if verbose:
        click.echo("  Checking for misplaced backend files...")
    backend_known_files = structure.get("backend_known_files", {})
    misplaced = []
    if backend_dir.exists():
        for filename, correct_path in backend_known_files.items():
            wrong_location = backend_dir / filename
            correct_location = backend_dir / correct_path

            if wrong_location.exists() and wrong_location.is_file():
                if correct_location.exists():
                    misplaced.append(
                        f"'{filename}' exists at backend/ root but also at correct location '{correct_path}'"
                    )
                else:
                    misplaced.append(f"backend/{filename} should be at backend/{correct_path}")

    if verbose:
        if misplaced:
            click.echo(f"    ✗ Found {len(misplaced)} misplaced file(s)")
        else:
            click.echo("    ✓ No misplaced files")

    if is_isolated:
        issues.extend(misplaced)
    elif misplaced and verbose:
        for m in misplaced:
            click.echo(f"      → {m}")

    # Check for files that can_be_folder violations
    if verbose:
        click.echo("  Checking for file/folder conflicts...")
    backend_files_config = _flatten_structure(structure.get("backend_files", {}))
    conflicts = []
    if backend_dir.exists():
        for path, config in backend_files_config.items():
            if not config.get("can_be_folder", False):
                continue

            file_path = backend_dir / path
            folder_path = backend_dir / path.replace(".py", "")

            if file_path.exists() and folder_path.exists():
                conflicts.append(f"Both 'backend/{path}' and 'backend/{path.replace('.py', '/')}' exist - pick one")

    if verbose:
        if conflicts:
            click.echo(f"    ✗ Found {len(conflicts)} conflict(s)")
        else:
            click.echo("    ✓ No conflicts")

    if is_isolated:
        issues.extend(conflicts)
    elif conflicts and verbose:
        for c in conflicts:
            click.echo(f"      → {c}")

    # Show progress toward isolation for legacy products
    if not is_isolated and verbose:
        click.echo("  Progress toward isolation...")

        # Key isolation files to check
        isolation_files = [
            ("api/dtos.py", "DTOs defined"),
            ("api/api.py", "Facade API"),
            ("presentation/views.py", "DRF views in presentation/"),
            ("presentation/serializers.py", "Serializers in presentation/"),
            ("presentation/urls.py", "URLs in presentation/"),
        ]

        present = 0
        total = len(isolation_files)
        for path, label in isolation_files:
            exists = _check_file_exists(backend_dir, path)
            if exists:
                present += 1
                click.echo(f"    ✓ {label}")
            else:
                click.echo(f"    ○ {label}")

        click.echo(f"    ({present}/{total} isolation requirements met)")

    return issues


@cli.command(name="product:bootstrap", help="Scaffold a new product with canonical structure")
@click.argument("name")
@click.option("--dry-run", is_flag=True, help="Show what would be created without creating")
@click.option("--force", is_flag=True, help="Overwrite existing files")
def cmd_bootstrap(name: str, dry_run: bool, force: bool) -> None:
    """Create a new product with the canonical structure."""
    bootstrap_product(name, dry_run, force)


@cli.command(name="product:lint", help="Check product structure for misplaced files")
@click.argument("name")
def cmd_lint(name: str) -> None:
    """Lint a product's structure."""
    click.echo(f"Linting product '{name}'...\n")

    issues = lint_product(name, verbose=True)

    click.echo("")
    if not issues:
        click.echo("✓ All checks passed")
        return

    click.echo("Issues:\n")
    for issue in issues:
        click.echo(f"  • {issue}")

    raise SystemExit(1)
