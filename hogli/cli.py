from __future__ import annotations

import os
import json
import shlex
import subprocess
import importlib.util
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, NoReturn, Optional

import typer

HEDGEHOG_ART = (
    """
    ╭────────────────────────────────────────────────╮
    │                                                │
    │          .-"""
    """.                hogli        │
    │        .'           '.                         │
    │       /   O      O    \\      PostHog          │
    │      |                 |     Developer         │
    │      |    \\.  ,  ./    |     CLI              │
    │       \\    " `--' "    /                      │
    │        '.           .'                         │
    │          `-......-'                            │
    │                                                │
    ╰────────────────────────────────────────────────╯
"""
)

app = typer.Typer(
    name="hogli",
    help="Unified developer experience for the PostHog monorepo.",
    pretty_exceptions_enable=False,
    rich_markup_mode="rich",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = REPO_ROOT / "bin"
PHW_SCRIPT = BIN_DIR / "phw"

EMOJI_SPARKLE = "✨"
EMOJI_RUNNING = "🚀"
EMOJI_OK = "✅"
EMOJI_HOG = "🐗"
EMOJI_ERROR = "💥"


class CommandError(RuntimeError):
    """Raised when a child command fails."""


@dataclass
class ProductInfo:
    slug: str
    package_name: str | None
    has_frontend: bool
    has_backend: bool


def _echo_heading(message: str) -> None:
    typer.echo(typer.style(f"{EMOJI_SPARKLE} {message}", bold=True))


def _print_step(message: str) -> None:
    typer.echo(typer.style(f"{EMOJI_RUNNING} {message}", fg=typer.colors.BLUE))


def _print_success(message: str) -> None:
    typer.echo(typer.style(f"{EMOJI_OK} {message}", fg=typer.colors.GREEN))


def _fail_with_message(error: CommandError) -> NoReturn:
    typer.echo(typer.style(f"{EMOJI_ERROR} {error}", fg=typer.colors.RED, bold=True))
    raise typer.Exit(1) from error


def _run(command: Sequence[str], *, env: dict[str, str] | None = None, description: str | None = None) -> None:
    display = " ".join(command)
    detail = f" {description}" if description else ""
    _print_step(f"{display}{detail}")
    try:
        subprocess.run(command, cwd=REPO_ROOT, env={**os.environ, **(env or {})}, check=True)
    except FileNotFoundError as exc:  # pragma: no cover - dependent on developer env
        raise CommandError(f"Command not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise CommandError(f"Command '{display}' failed with exit code {exc.returncode}") from exc
    _print_success("Done")


def _run_phw(args: Sequence[str]) -> None:
    if not PHW_SCRIPT.exists():
        raise CommandError("Worktree helper script is missing from bin/phw")
    quoted_args = " ".join(shlex.quote(arg) for arg in args)
    command = [
        "bash",
        "-lc",
        f"source {shlex.quote(str(PHW_SCRIPT))} && phw {quoted_args}".rstrip(),
    ]
    _run(command, description="(phw worktree helper)")


def _run_pytest(args: Sequence[str]) -> None:
    _run(["pytest", *args], description="(Python tests)")


def _run_jest(args: Sequence[str]) -> None:
    _run(["pnpm", "--filter", "@posthog/frontend", "run", "test", *args], description="(Frontend tests)")


def _run_python_lint(fix: bool) -> None:
    args = ["check"] if not fix else ["check", "--fix"]
    _run([str(BIN_DIR / "ruff.sh"), *args, "."], description="(Python lint)")


def _run_js_lint(fix: bool) -> None:
    command = ["pnpm", "--filter", "@posthog/frontend", "run", "lint"]
    if fix:
        command = ["pnpm", "--filter", "@posthog/frontend", "run", "format"]
    _run(command, description="(Frontend lint)")


def _run_python_fmt() -> None:
    _run([str(BIN_DIR / "ruff.sh"), "format", "."], description="(Python format)")


def _run_js_fmt() -> None:
    _run(["pnpm", "--filter", "@posthog/frontend", "run", "format"], description="(Frontend format)")


def _run_frontend_build() -> None:
    _run(["pnpm", "--filter", "@posthog/frontend", "run", "build"], description="(Frontend build)")
    _run(
        ["pnpm", "--filter", "@posthog/frontend", "run", "typescript:check"],
        description="(TypeScript check)",
    )


@app.callback()
def main(
    _: bool = typer.Option(False, "--version", callback=lambda value: _show_version(value), is_eager=True),
) -> None:
    """Entry point for the CLI."""
    pass


def _show_version(value: bool) -> None:
    if not value:
        return
    typer.echo(typer.style(HEDGEHOG_ART, fg=typer.colors.CYAN, bold=True))
    typer.echo(typer.style("Version: PostHog hogli", fg=typer.colors.GREEN))
    raise typer.Exit()


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def up(ctx: typer.Context) -> None:
    """Start backend, product frontends, and infrastructure with mprocs."""

    typer.echo(f"{EMOJI_HOG}{EMOJI_SPARKLE} Launching PostHog stack via mprocs…")
    command = [str(BIN_DIR / "start"), *ctx.args]
    try:
        _run(command)
    except CommandError as error:
        _fail_with_message(error)


tests_app = typer.Typer(help="Testing workflows.")
app.add_typer(tests_app, name="test")


@tests_app.callback(invoke_without_command=True)
def test(
    ctx: typer.Context,
    scope: Annotated[
        str,
        typer.Option(
            "--scope",
            help="Which test suite to run (python or js). Pick one—running all tests takes 30+ minutes.",
            case_sensitive=False,
        ),
    ] = "python",
    pytest_args: Annotated[
        Optional[list[str]],
        typer.Option(
            "--pytest-arg",
            help="Additional arguments to forward to pytest (repeatable).",
        ),
    ] = None,
    jest_args: Annotated[
        Optional[list[str]],
        typer.Option(
            "--jest-arg",
            help="Additional arguments to forward to the frontend test runner (repeatable).",
        ),
    ] = None,
) -> None:
    """Run a specific test suite. Pick one—tests are slow and shouldn't run together."""

    if ctx.invoked_subcommand is not None:
        return

    normalized_scope = scope.lower()
    valid_scopes = {"python", "js"}
    if normalized_scope not in valid_scopes:
        raise typer.BadParameter("Scope must be one of: python, js")

    try:
        if normalized_scope == "python":
            pytest_forward = list(pytest_args or [])
            _run_pytest(pytest_forward)
        elif normalized_scope == "js":
            jest_forward = list(jest_args or [])
            _run_jest(jest_forward)
    except CommandError as error:
        _fail_with_message(error)


@tests_app.command("python")
def test_python(
    pytest_args: Annotated[
        list[str] | None,
        typer.Argument(
            help="Arguments forwarded directly to pytest (e.g. file paths or -k expressions).",
            metavar="PYTEST_ARG",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Run only the Python test suite with optional selectors."""

    try:
        _run_pytest(list(pytest_args or []))
    except CommandError as error:
        _fail_with_message(error)


@tests_app.command("js")
def test_js(
    jest_args: Annotated[
        list[str] | None,
        typer.Argument(
            help="Arguments forwarded to the frontend test runner (e.g. --watch or a path pattern).",
            metavar="JEST_ARG",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Run only the JavaScript test suite with optional selectors."""

    try:
        _run_jest(list(jest_args or []))
    except CommandError as error:
        _fail_with_message(error)


@app.command()
def lint(
    scope: str = typer.Option(
        "all",
        "--scope",
        help="Which linters to run (all, python, js).",
        case_sensitive=False,
    ),
    fix: bool = typer.Option(False, "--fix", help="Attempt to automatically fix lint issues when supported."),
) -> None:
    """Run code quality checks for Python and JavaScript."""

    normalized_scope = scope.lower()
    valid_scopes = {"all", "python", "js"}
    if normalized_scope not in valid_scopes:
        raise typer.BadParameter("Scope must be one of: all, python, js")

    try:
        if normalized_scope in {"all", "python"}:
            _run_python_lint(fix)
        if normalized_scope in {"all", "js"}:
            _run_js_lint(fix)
    except CommandError as error:
        _fail_with_message(error)


@app.command()
def fmt(
    scope: str = typer.Option(
        "all",
        "--scope",
        help="Which formatters to run (all, python, js).",
        case_sensitive=False,
    ),
) -> None:
    """Format Python and JavaScript code."""

    normalized_scope = scope.lower()
    valid_scopes = {"all", "python", "js"}
    if normalized_scope not in valid_scopes:
        raise typer.BadParameter("Scope must be one of: all, python, js")

    try:
        if normalized_scope in {"all", "python"}:
            _run_python_fmt()
        if normalized_scope in {"all", "js"}:
            _run_js_fmt()
    except CommandError as error:
        _fail_with_message(error)


@app.command()
def migrate() -> None:
    """Apply Django and ClickHouse migrations using the canonical script."""

    try:
        typer.echo(f"{EMOJI_HOG}{EMOJI_SPARKLE} Applying PostHog migrations…")
        _run([str(BIN_DIR / "migrate")])
    except CommandError as error:
        _fail_with_message(error)


@app.command()
def shell() -> None:
    """Drop into an activated Flox shell."""

    typer.echo(f"{EMOJI_HOG}{EMOJI_SPARKLE} Launching Flox environment shell…")
    try:
        os.execvp("flox", ["flox", "activate"])
    except FileNotFoundError as error:  # pragma: no cover - depends on local toolchain
        typer.echo(typer.style(f"{EMOJI_ERROR} flox command not found in PATH.", fg=typer.colors.RED))
        raise typer.Exit(1) from error


@app.command()
def build(
    scope: str = typer.Option(
        "all",
        "--scope",
        help="Which build targets to run (all, frontend).",
        case_sensitive=False,
    ),
) -> None:
    """Build JavaScript packages and run TypeScript compilation."""

    normalized_scope = scope.lower()
    valid_scopes = {"all", "frontend"}
    if normalized_scope not in valid_scopes:
        raise typer.BadParameter("Scope must be one of: all, frontend")

    try:
        if normalized_scope in {"all", "frontend"}:
            _run_frontend_build()
    except CommandError as error:
        _fail_with_message(error)


@app.command()
def services(
    follow: bool = typer.Option(False, "--follow", help="Stream docker-compose logs after the services are up."),
    rebuild: bool = typer.Option(False, "--rebuild", help="Recreate containers even if they already exist."),
    down: bool = typer.Option(False, "--down", help="Tear down the infrastructure services."),
) -> None:
    """Start or stop the shared infrastructure services (Postgres, ClickHouse, Redis, Kafka)."""

    compose_file = str(REPO_ROOT / "docker-compose.dev.yml")
    services = ["db", "clickhouse", "redis", "redis7", "zookeeper", "kafka"]

    try:
        if down:
            _run(["docker", "compose", "-f", compose_file, "down"], description="(Stop infra services)")
            return

        command: list[str] = ["docker", "compose", "-f", compose_file, "up", "-d", *services]
        if rebuild:
            command.insert(command.index("up") + 1, "--force-recreate")
        _run(command, description="(Start infra services)")
        if follow:
            _run(["docker", "compose", "-f", compose_file, "logs", "-f", *services], description="(Follow logs)")
    except CommandError as error:
        _fail_with_message(error)


@app.command()
def check(
    linting: bool = typer.Option(True, "--lint/--skip-lint", help="Toggle running Python and JS linters (fast)."),
    build_assets: bool = typer.Option(True, "--build/--skip-build", help="Toggle building the frontend packages."),
) -> None:
    """Run fast quality checks: lint + build. Run tests separately—they're slow.

    This skips test runs because tests take 15+ minutes and shouldn't be bundled with lint/build.
    Run hogli test python or hogli test js separately in another terminal.
    """

    typer.echo(f"{EMOJI_HOG}{EMOJI_SPARKLE} Running fast quality checks (lint + build)…")
    typer.echo(typer.style("Tip: run tests separately with hogli test python or hogli test js", fg=typer.colors.YELLOW))
    try:
        if linting:
            _run_python_lint(False)
            _run_js_lint(False)
        if build_assets:
            _run_frontend_build()
    except CommandError as error:
        _fail_with_message(error)


@app.command(
    "worktree",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def worktree(ctx: typer.Context) -> None:
    """Delegate to the phw helper for isolated worktree management."""

    try:
        _run_phw(list(ctx.args))
    except CommandError as error:
        _fail_with_message(error)


products_app = typer.Typer(help="Product catalog utilities.")
app.add_typer(products_app, name="products")


@products_app.command("list")
def list_products(json_output: bool = typer.Option(False, "--json", help="Output as JSON.")) -> None:
    """Enumerate available product packages across frontend and backend."""

    infos = _discover_products()
    if json_output:
        typer.echo(json.dumps([info.__dict__ for info in infos], indent=2))
        return

    if not infos:
        typer.echo(f"{EMOJI_ERROR} No product packages found.")
        return

    typer.echo(f"{EMOJI_HOG}{EMOJI_SPARKLE} Discovering product packages…")
    header = f"{'Slug':<25}{'Package':<40}{'Frontend':<10}{'Backend':<10}"
    _echo_heading(header)
    for info in infos:
        package_display = info.package_name or "—"
        typer.echo(f"{info.slug:<25}{package_display:<40}{str(info.has_frontend):<10}{str(info.has_backend):<10}")


def _discover_products() -> list[ProductInfo]:
    products_dir = REPO_ROOT / "products"
    if not products_dir.exists():
        return []

    infos: list[ProductInfo] = []
    for candidate in sorted(p for p in products_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
        package_json = candidate / "package.json"
        package_name: str | None = None
        has_frontend = package_json.exists()
        if package_json.exists():
            try:
                package_name = json.loads(package_json.read_text()).get("name")
            except json.JSONDecodeError:
                package_name = None
        module_name = f"products.{candidate.name}"
        has_backend = importlib.util.find_spec(module_name) is not None
        infos.append(ProductInfo(candidate.name, package_name, has_frontend, has_backend))
    return infos


if __name__ == "__main__":
    app()
