"""CLI commands for product scaffolding and linting."""

from __future__ import annotations

import click
from hogli.cli import cli

from .lint import lint_all_products, lint_product
from .scaffold import bootstrap_product


@cli.command(name="product:bootstrap", help="Scaffold a new product with canonical structure")
@click.argument("name")
@click.option("--dry-run", is_flag=True, help="Show what would be created without creating")
@click.option("--force", is_flag=True, help="Overwrite existing files")
def cmd_bootstrap(name: str, dry_run: bool, force: bool) -> None:
    bootstrap_product(name, dry_run, force)


@cli.command(name="product:lint", help="Check product structure for misplaced files")
@click.argument("name", required=False)
@click.option("--all", "lint_all", is_flag=True, help="Lint all products")
def cmd_lint(name: str | None, lint_all: bool) -> None:
    if lint_all:
        lint_all_products()
        return

    if not name:
        raise click.UsageError("Provide a product name or use --all")

    click.echo(f"Linting product '{name}'...\n")
    issues = lint_product(name, verbose=True, detailed=True)
    click.echo("")

    if not issues:
        click.echo("✓ All checks passed")
        return

    click.echo("Issues:\n")
    for issue in issues:
        click.echo(f"  • {issue}")
    raise SystemExit(1)
