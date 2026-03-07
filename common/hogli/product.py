"""Product scaffolding and linting commands."""

from __future__ import annotations

import re
import json
from collections.abc import Callable
from pathlib import Path

import yaml
import click
from hogli.core.cli import cli

REPO_ROOT = Path(__file__).parent.parent.parent
STRUCTURE_FILE = Path(__file__).parent / "product_structure.yaml"
PRODUCTS_DIR = REPO_ROOT / "products"
TACH_TOML = REPO_ROOT / "tach.toml"
FRONTEND_PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
DJANGO_SETTINGS = REPO_ROOT / "posthog" / "settings" / "web.py"


def load_structure() -> dict:
    """Load the canonical product structure from YAML."""
    return yaml.safe_load(STRUCTURE_FILE.read_text())


def _flatten_structure(files: dict, prefix: str = "", result: dict | None = None) -> dict[str, dict]:
    """
    Flatten nested structure into flat paths.
    e.g., {"facade/": {"api.py": {...}}} -> {"facade/api.py": {...}}
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


def _add_to_tach_toml(product_name: str, *, dry_run: bool) -> None:
    """Add product module to tach.toml as an isolated product."""
    module_path = f"products.{product_name}"
    block = f'\n[[modules]]\npath = "{module_path}"\ndepends_on = ["posthog"]\nlayer = "products"\n'

    _register_in_file(
        TACH_TOML,
        "tach.toml",
        f'path = "{module_path}"',
        lambda content: content.rstrip() + "\n" + block,
        dry_run=dry_run,
    )


def _register_in_file(
    file_path: Path, label: str, needle: str, write_fn: Callable[[str], str | None], *, dry_run: bool
) -> None:
    """Register a product entry in a config file. Skips if needle already present."""
    if not file_path.exists():
        return

    content = file_path.read_text()
    if needle in content:
        click.echo(f"\n  Already in {label}: {needle}")
        return

    if dry_run:
        click.echo(f"\n  Would add to {label}: {needle}")
        return

    result = write_fn(content)
    if result is not None:
        file_path.write_text(result)
        click.echo(f"\n  Added to {label}: {needle}")


def _add_to_frontend_package_json(product_name: str, *, dry_run: bool) -> None:
    """Add product workspace dependency to frontend/package.json."""
    pkg_name = f"@posthog/products-{product_name.replace('_', '-')}"

    def write(content: str) -> str:
        data = json.loads(content)
        deps = data.get("dependencies", {})
        deps[pkg_name] = "workspace:*"
        data["dependencies"] = dict(sorted(deps.items()))
        return json.dumps(data, indent=4) + "\n"

    _register_in_file(FRONTEND_PACKAGE_JSON, "frontend/package.json", pkg_name, write, dry_run=dry_run)


def _add_to_django_settings(product_name: str, *, dry_run: bool) -> None:
    """Add product app config to INSTALLED_APPS in Django settings."""
    pascal_name = "".join(word.capitalize() for word in product_name.split("_"))
    app_config = f"products.{product_name}.backend.apps.{pascal_name}Config"

    def write(content: str) -> str | None:
        # Find the last product entry in INSTALLED_APPS and insert after it
        pattern = r'(    "products\.[^"]+",\n)(?!    "products\.)'
        match = list(re.finditer(pattern, content))
        if not match:
            click.echo(f"\n  Could not find INSTALLED_APPS products section — add manually: {app_config}")
            return None
        insert_pos = match[-1].end()
        return content[:insert_pos] + f'    "{app_config}",\n' + content[insert_pos:]

    _register_in_file(DJANGO_SETTINGS, "Django settings", app_config, write, dry_run=dry_run)


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

    _add_to_tach_toml(name, dry_run=dry_run)
    _add_to_frontend_package_json(name, dry_run=dry_run)
    _add_to_django_settings(name, dry_run=dry_run)


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


def _is_isolated_product(backend_dir: Path) -> bool:
    contracts_file = backend_dir / "facade" / "contracts.py"
    contracts_folder = backend_dir / "facade" / "contracts"
    return contracts_file.exists() or contracts_folder.exists()


def lint_product(name: str, verbose: bool = True) -> list[str]:
    """
    Lint a product's structure. Returns list of issues found.

    Runs in two modes based on whether the product has backend/facade/contracts.py:
      strict  — isolated product, all structure rules enforced
      lenient — legacy product, subset of rules enforced (see product_structure.yaml)

    Both modes fail on violations. Lenient just checks fewer things.
    """
    product_dir = PRODUCTS_DIR / name
    backend_dir = product_dir / "backend"

    if not product_dir.exists():
        raise click.ClickException(f"Product '{name}' not found at {product_dir}")

    structure = load_structure()
    issues: list[str] = []

    is_isolated = _is_isolated_product(backend_dir)
    mode = "strict" if is_isolated else "lenient"
    required_key = "required" if is_isolated else "required_lenient"

    if verbose:
        click.echo(f"  mode: {mode}" + (" (has backend/facade/contracts.py)" if is_isolated else " (legacy)"))

    # 1. Required root files
    if verbose:
        click.echo("  required root files...")
    root_files = structure.get("root_files", {})
    missing_root = []
    for filename, config in root_files.items():
        if config.get(required_key, False):
            if not (product_dir / filename).exists():
                missing_root.append(filename)

    if verbose:
        if missing_root:
            click.echo(f"    ✗ missing: {', '.join(missing_root)}")
        else:
            click.echo("    ✓ ok")

    for f in missing_root:
        issues.append(f"Missing required root file: {f}")

    # 2. backend:test in package.json (if product has backend/)
    if backend_dir.exists():
        package_json = product_dir / "package.json"
        if package_json.exists():
            try:
                pkg_data = json.loads(package_json.read_text())
                has_backend_test = "backend:test" in pkg_data.get("scripts", {})
            except json.JSONDecodeError:
                has_backend_test = False
                issues.append("package.json is not valid JSON")
        else:
            has_backend_test = False

        if verbose:
            click.echo("  backend:test in package.json...")
        if not has_backend_test:
            issues.append(
                "Product has backend/ but package.json is missing 'backend:test' script — "
                "turbo cannot discover this product for testing"
            )
            if verbose:
                click.echo("    ✗ missing")
        elif verbose:
            click.echo("    ✓ ok")

    # 3. Misplaced backend files (strict only — legacy products have flat structure by design)
    if is_isolated:
        if verbose:
            click.echo("  misplaced backend files...")
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
                click.echo(f"    ✗ {len(misplaced)} misplaced file(s)")
                for m in misplaced:
                    click.echo(f"      → {m}")
            else:
                click.echo("    ✓ ok")

        issues.extend(misplaced)

    # 4. File/folder conflicts
    if verbose:
        click.echo("  file/folder conflicts...")
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
            click.echo(f"    ✗ {len(conflicts)} conflict(s)")
            for c in conflicts:
                click.echo(f"      → {c}")
        else:
            click.echo("    ✓ ok")

    issues.extend(conflicts)

    # 5. Isolation progress (informational, not enforced)
    if not is_isolated and verbose and backend_dir.exists():
        click.echo("  isolation progress...")

        isolation_files = [
            ("facade/contracts.py", "contracts"),
            ("facade/api.py", "facade"),
            ("presentation/views.py", "views"),
            ("presentation/serializers.py", "serializers"),
            ("presentation/urls.py", "urls"),
        ]

        checks = [_check_file_exists(backend_dir, path) for path, _ in isolation_files]
        present = sum(checks)
        labels = [f"{'✓' if ok else '○'} {label}" for ok, (_, label) in zip(checks, isolation_files)]
        click.echo(f"    {', '.join(labels)} ({present}/{len(isolation_files)})")

    return issues


@cli.command(name="product:bootstrap", help="Scaffold a new product with canonical structure")
@click.argument("name")
@click.option("--dry-run", is_flag=True, help="Show what would be created without creating")
@click.option("--force", is_flag=True, help="Overwrite existing files")
def cmd_bootstrap(name: str, dry_run: bool, force: bool) -> None:
    """Create a new product with the canonical structure."""
    bootstrap_product(name, dry_run, force)


@cli.command(name="product:lint", help="Check product structure for misplaced files")
@click.argument("name", required=False)
@click.option("--all", "lint_all", is_flag=True, help="Lint all products")
def cmd_lint(name: str | None, lint_all: bool) -> None:
    """Lint a product's structure."""
    if lint_all:
        _lint_all_products()
        return

    if not name:
        raise click.UsageError("Provide a product name or use --all")

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


def _lint_all_products() -> None:
    product_dirs = sorted(
        d
        for d in PRODUCTS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith((".", "_")) and (d / "__init__.py").exists()
    )

    strict = [d.name for d in product_dirs if _is_isolated_product(d / "backend")]
    lenient = [d.name for d in product_dirs if not _is_isolated_product(d / "backend")]

    click.echo(f"Linting {len(product_dirs)} products ({len(strict)} strict, {len(lenient)} lenient)")
    click.echo("Checks: required root files, backend:test script, misplaced files, file/folder conflicts\n")

    failed: list[str] = []

    for product_dir in product_dirs:
        click.echo(f"─ {product_dir.name}")
        issues = lint_product(product_dir.name, verbose=True)

        if issues:
            failed.append(product_dir.name)

        click.echo("")

    if failed:
        click.echo(f"✗ {len(failed)} product(s) failed: {', '.join(failed)}")
        raise SystemExit(1)

    click.echo(f"✓ All {len(product_dirs)} products passed")
