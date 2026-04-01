"""Unified build command with smart change detection."""

from __future__ import annotations

import fnmatch
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
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

    # Working tree: staged + unstaged + untracked in one call
    try:
        status = subprocess.check_output(
            ["git", "status", "--porcelain", "--no-renames"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in status.splitlines():
            if len(line) > 3:
                # Porcelain format: "XY filename" — 2-char status + space + path
                changed.add(line[3:])
    except subprocess.CalledProcessError:
        pass

    return changed


def _match_pipelines(changed_files: set[str]) -> list[Pipeline]:
    """Determine which pipelines need to run based on changed files."""
    return [p for p in PIPELINES if _pipeline_matches(p, changed_files)]


def _pipeline_matches(pipeline: Pipeline, changed_files: set[str]) -> bool:
    """Check if any changed file matches any of the pipeline's trigger globs."""
    return any(fnmatch.fnmatch(path, trigger) for path in changed_files for trigger in pipeline.triggers)


def _run_pipeline(pipeline: Pipeline) -> tuple[bool, str]:
    """Run a single pipeline. Returns (success, captured output)."""
    bin_hogli = str(REPO_ROOT / "bin" / "hogli")
    result = subprocess.run(
        [bin_hogli, pipeline.command],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return (result.returncode == 0, result.stdout + result.stderr)


def _print_result(name: str, success: bool, output: str) -> None:
    """Print the result of a single pipeline run."""
    click.secho(f"--- {name} ---", fg="blue", bold=True)
    if output.strip():
        click.echo(output.rstrip())
    if success:
        click.secho(f"  OK: {name}", fg="green")
    else:
        click.secho(f"  FAILED: {name}", fg="red")


def _run_pipelines_parallel(pipelines: list[Pipeline]) -> list[str]:
    """Run pipelines in parallel, printing output as each completes. Returns failed names."""
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=min(len(pipelines), 4)) as executor:
        future_to_pipeline = {executor.submit(_run_pipeline, p): p for p in pipelines}
        for future in as_completed(future_to_pipeline):
            p = future_to_pipeline[future]
            success, output = future.result()
            _print_result(p.name, success, output)
            if not success:
                failed.append(p.name)
    return failed


def _run_pipelines_sequential(pipelines: list[Pipeline]) -> list[str]:
    """Run pipelines sequentially. Returns failed names."""
    failed: list[str] = []
    for p in pipelines:
        success, output = _run_pipeline(p)
        _print_result(p.name, success, output)
        if not success:
            failed.append(p.name)
    return failed


@cli.command(name="build", help="Run code generation pipelines (smart change detection by default)")
@click.option("--force", is_flag=True, help="Rebuild all pipelines unconditionally")
@click.option("--dry-run", is_flag=True, help="Show what would be rebuilt without running")
@click.option("--list", "list_pipelines", is_flag=True, help="List all available pipelines")
@click.option("--sequential", is_flag=True, help="Run pipelines sequentially instead of in parallel")
def build(force: bool, dry_run: bool, list_pipelines: bool, sequential: bool) -> None:
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

    if dry_run:
        click.echo(f"Would build {len(pipelines)} pipeline(s):")
        for p in pipelines:
            marker = " (requires running services)" if p.needs_services else ""
            click.echo(f"  {p.name} -> hogli {p.command}{marker}")
        return

    click.echo(f"Building {len(pipelines)} pipeline(s):")
    for p in pipelines:
        marker = " (requires running services)" if p.needs_services else ""
        click.echo(f"  {p.name} -> hogli {p.command}{marker}")

    click.echo()

    if sequential or len(pipelines) == 1:
        failed = _run_pipelines_sequential(pipelines)
    else:
        failed = _run_pipelines_parallel(pipelines)

    click.echo()
    if failed:
        click.secho(f"Build completed with failures: {', '.join(failed)}", fg="red")
        raise SystemExit(1)
    else:
        click.secho("All pipelines completed successfully.", fg="green")
