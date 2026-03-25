"""Product lint runner."""

from __future__ import annotations

import click

from .checks import CHECKS, CheckContext, is_isolated_product
from .paths import PRODUCTS_DIR, load_structure


def lint_product(name: str, verbose: bool = True, detailed: bool = False, structure: dict | None = None) -> list[str]:
    """
    Lint a product's structure. Returns list of issues found.

    Runs in two modes based on whether the product has backend/facade/contracts.py:
      strict  — isolated product, all structure rules enforced
      lenient — legacy product, subset of rules enforced (see product_structure.yaml)

    Set detailed=True (single-product run) for richer isolation progress output.
    Pass structure= to avoid re-parsing product_structure.yaml on every call (useful in --all mode).
    """
    product_dir = PRODUCTS_DIR / name
    backend_dir = product_dir / "backend"

    if not product_dir.exists():
        raise click.ClickException(f"Product '{name}' not found at {product_dir}")

    isolated = is_isolated_product(backend_dir)
    mode = "strict" if isolated else "lenient"

    if verbose:
        click.echo(f"  mode: {mode}" + (" (has backend/facade/contracts.py)" if isolated else " (legacy)"))

    ctx = CheckContext(
        name=name,
        product_dir=product_dir,
        backend_dir=backend_dir,
        is_isolated=isolated,
        structure=structure or load_structure(),
        detailed=detailed,
    )

    issues: list[str] = []
    for check in CHECKS:
        if not check.should_run(ctx):
            continue
        if verbose:
            click.echo(f"  {check.label}...")
        result = check.run(ctx)
        if result.skip:
            continue
        if verbose:
            for line in result.lines:
                click.echo(f"    {line}")
        issues.extend(result.issues)

    return issues


def lint_all_products() -> None:
    product_dirs = sorted(
        d
        for d in PRODUCTS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith((".", "_")) and (d / "__init__.py").exists()
    )

    strict = [d.name for d in product_dirs if is_isolated_product(d / "backend")]
    lenient = [d.name for d in product_dirs if not is_isolated_product(d / "backend")]

    click.echo(f"Linting {len(product_dirs)} products ({len(strict)} strict, {len(lenient)} lenient)")
    click.echo(
        "Checks: required root files, package.json scripts (presence + content), misplaced files (strict), "
        "file/folder conflicts, tach boundaries (+ interfaces for strict), isolation progress (lenient)\n"
    )

    structure = load_structure()

    failed: list[str] = []
    for product_dir in product_dirs:
        click.echo(f"─ {product_dir.name}")
        issues = lint_product(product_dir.name, verbose=True, detailed=False, structure=structure)
        if issues:
            failed.append(product_dir.name)
        click.echo("")

    if failed:
        click.echo(f"✗ {len(failed)} product(s) failed: {', '.join(failed)}")
        raise SystemExit(1)

    click.echo(f"✓ All {len(product_dirs)} products passed")
