"""Unified build command with smart change detection."""

from __future__ import annotations

import fnmatch
import subprocess
from dataclasses import dataclass

import click
from hogli.core.cli import cli
from hogli.core.manifest import REPO_ROOT


@dataclass(frozen=True)
class Pipeline:
    name: str
    command: str
    triggers: tuple[str, ...]
    needs_services: bool = False


PIPELINES: tuple[Pipeline, ...] = (
    Pipeline(
        name="schema",
        command="build:schema",
        triggers=(
            "frontend/src/queries/schema/*",
            "posthog/schema_migrations/*",
        ),
    ),
    Pipeline(
        name="openapi",
        command="build:openapi",
        triggers=(
            "posthog/api/*",
            "ee/api/*",
            "products/*/backend/api/*",
            "products/*/backend/presentation/*",
            "products/*/mcp/tools.yaml",
            "services/mcp/definitions/*",
        ),
        needs_services=True,
    ),
    Pipeline(
        name="grammar",
        command="build:grammar",
        triggers=("posthog/hogql/grammar/*",),
    ),
    Pipeline(
        name="taxonomy",
        command="build:taxonomy-json",
        triggers=("posthog/taxonomy/*",),
    ),
    Pipeline(
        name="products",
        command="build:products",
        triggers=("products/*/frontend/*",),
    ),
    Pipeline(
        name="skills",
        command="build:skills",
        triggers=("products/*/skills/*",),
    ),
    Pipeline(
        name="schema-mcp",
        command="build:schema-mcp",
        triggers=("services/mcp/src/*",),
    ),
)


def _get_changed_files() -> set[str]:
    """Get all files changed on the current branch vs master, plus uncommitted changes."""
    changed: set[str] = set()

    # Branch changes vs merge-base with master
    try:
        merge_base = subprocess.check_output(
            ["git", "merge-base", "HEAD", "master"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        branch_diff = subprocess.check_output(
            ["git", "diff", "--name-only", f"{merge_base}...HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if branch_diff:
            changed.update(branch_diff.splitlines())
    except subprocess.CalledProcessError:
        pass

    # Uncommitted changes (staged + unstaged)
    for diff_args in (["--staged"], []):
        try:
            result = subprocess.check_output(
                ["git", "diff", "--name-only", *diff_args],
                cwd=REPO_ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            if result:
                changed.update(result.splitlines())
        except subprocess.CalledProcessError:
            pass

    # Untracked files
    try:
        result = subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if result:
            changed.update(result.splitlines())
    except subprocess.CalledProcessError:
        pass

    return changed


def _match_pipelines(changed_files: set[str]) -> list[Pipeline]:
    """Determine which pipelines need to run based on changed files."""
    return [p for p in PIPELINES if _pipeline_matches(p, changed_files)]


def _pipeline_matches(pipeline: Pipeline, changed_files: set[str]) -> bool:
    """Check if any changed file matches any of the pipeline's trigger globs."""
    return any(fnmatch.fnmatch(path, trigger) for path in changed_files for trigger in pipeline.triggers)


def _run_pipeline(pipeline: Pipeline) -> bool:
    """Run a single pipeline. Returns True on success."""
    bin_hogli = str(REPO_ROOT / "bin" / "hogli")
    try:
        subprocess.run([bin_hogli, pipeline.command], cwd=REPO_ROOT, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


@cli.command(name="build", help="Run code generation pipelines (smart change detection by default)")
@click.option("--force", is_flag=True, help="Rebuild all pipelines unconditionally")
@click.option("--dry-run", is_flag=True, help="Show what would be rebuilt without running")
@click.option("--list", "list_pipelines", is_flag=True, help="List all available pipelines")
def build(force: bool, dry_run: bool, list_pipelines: bool) -> None:
    """Unified build command with smart change detection."""
    if list_pipelines:
        click.echo("Available build pipelines:\n")
        for p in PIPELINES:
            services_note = " (requires running services)" if p.needs_services else ""
            click.echo(f"  {p.name:<12} hogli {p.command}{services_note}")
            for trigger in p.triggers:
                click.echo(f"  {'':<12}   {trigger}")
        return

    if force:
        pipelines = list(PIPELINES)
    else:
        changed = _get_changed_files()
        if not changed:
            click.echo("Nothing to rebuild -- no changes detected.")
            return
        pipelines = _match_pipelines(changed)
        if not pipelines:
            click.echo(f"Nothing to rebuild -- {len(changed)} changed file(s) don't match any build pipeline.")
            return

    click.echo(f"Building {len(pipelines)} pipeline(s):")
    for p in pipelines:
        marker = " (requires running services)" if p.needs_services else ""
        click.echo(f"  {p.name} -> hogli {p.command}{marker}")

    if dry_run:
        return

    click.echo()

    failed: list[str] = []
    for p in pipelines:
        click.secho(f"--- {p.name} ---", fg="blue", bold=True)
        if not _run_pipeline(p):
            failed.append(p.name)
            click.secho(f"  FAILED: {p.name}", fg="red")

    click.echo()
    if failed:
        click.secho(f"Build completed with failures: {', '.join(failed)}", fg="red")
        raise SystemExit(1)
    else:
        click.secho("All pipelines completed successfully.", fg="green")
