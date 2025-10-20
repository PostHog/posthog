from __future__ import annotations

import os
import json
import shlex
import subprocess
import importlib.util
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, NoReturn

import yaml
import typer

HEDGEHOG_ART = r"""






                           00     0
                      000F  F0FF  0000  00
                000FF 00  FF00  FFF0 FF F0F
                 FF   000         00   00 0F 00
           FF00FF000                        000
             F0                               F
          00F0                                00
        FFF0                   0FFFF   FFFFFFF0F
          00                  0F    FF         00
        00                     0F               0F
      FFFF0                      F0       0F0     FFF
        F0                      00         0         F000
       0F                      F0                     F00
      00FF0                   F0                     F0
         F                  FF                000FFFF
        0F00              FF                  000
        00F0           FFF                0FF
          F       FFFFF         0    00 FFF
          0FF00FF               00   0F0  FF
             00    00000000FFFFF00F   0FF0  000
              0FFFF00000000       0FF   00FF00
                                     FFF0
"""

app = typer.Typer(
    name="hogli",
    help="Unified developer experience for the PostHog monorepo.",
    pretty_exceptions_enable=False,
    rich_markup_mode="rich",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = REPO_ROOT / "bin"
PHW_SCRIPT = BIN_DIR / "phw"
MANIFEST_FILE = Path(__file__).parent / "scripts_manifest.yaml"

EMOJI_SPARKLE = "✨"
EMOJI_RUNNING = "🚀"
EMOJI_OK = "✅"
EMOJI_HOG = "🐗"
EMOJI_ERROR = "💥"


def _load_manifest() -> dict:
    """Load scripts manifest from YAML file."""
    if not MANIFEST_FILE.exists():
        return {}
    with open(MANIFEST_FILE) as f:
        return yaml.safe_load(f) or {}


class CommandError(RuntimeError):
    """Raised when a child command fails."""


@dataclass
class ProductInfo:
    slug: str
    package_name: str | None
    has_frontend: bool
    has_backend: bool


def _group_commands_by_category() -> dict[str, list[tuple[str, str]]]:
    """Group all registered commands by their category prefix."""
    manifest = _load_manifest()

    grouped = defaultdict(list)

    # Group commands from manifest
    for section_name, commands in manifest.items():
        if section_name == "metadata":
            continue
        if not isinstance(commands, dict):
            continue

        for cli_name, config in commands.items():
            if isinstance(config, dict):
                description = config.get("description", "")
                grouped[section_name].append((cli_name, description))

    return grouped


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


@app.command("categories")
def show_categories() -> None:
    """Show all available commands grouped by category.

    Groups commands with descriptive category headers (like git help).
    """
    manifest = _load_manifest()
    metadata = manifest.get("metadata", {}).get("categories", {})

    grouped = _group_commands_by_category()

    # Sort by order from metadata
    sorted_categories = sorted(grouped.items(), key=lambda x: metadata.get(x[0], {}).get("order", 999))

    for category, commands in sorted_categories:
        category_desc = metadata.get(category, {}).get("title", category.replace("_", " "))
        typer.echo()
        typer.echo(typer.style(f"{category_desc}", fg=typer.colors.CYAN, bold=True))
        for cli_name, description in sorted(commands):
            # Format: "  command    description (truncated)"
            typer.echo(f"   {cli_name:30} {description[:50]}...")


@app.command("dev:up", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def dev_up(ctx: typer.Context) -> None:
    """Start full PostHog dev stack via mprocs.

    Justification: "up" is vague—could mean many things. "dev:up" explicitly
    indicates we're starting the development environment stack.
    """
    typer.echo(f"{EMOJI_HOG}{EMOJI_SPARKLE} Launching PostHog stack via mprocs…")
    command = [str(BIN_DIR / "start"), *ctx.args]
    try:
        _run(command)
    except CommandError as error:
        _fail_with_message(error)


@app.command("test:python")
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
    """Run Python test suite.

    Justification: Flatten nested "test python" into "test:python" for consistent
    verb:noun naming. All tests should be visible at same level.
    """
    try:
        _run_pytest(list(pytest_args or []))
    except CommandError as error:
        _fail_with_message(error)


@app.command("test:js")
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
    """Run JavaScript test suite.

    Justification: Flatten nested "test js" into "test:js" for consistency.
    """
    try:
        _run_jest(list(jest_args or []))
    except CommandError as error:
        _fail_with_message(error)


@app.command("lint:check")
def lint_check(
    scope: str = typer.Option(
        "all",
        "--scope",
        help="Which linters to run (all, python, js).",
        case_sensitive=False,
    ),
) -> None:
    """Run code quality checks for Python and JavaScript.

    Justification: "lint" alone is vague (lint what? the linter?). "lint:check"
    is explicit: lint CHECK. Separate --fix into dedicated lint:fix command.
    """
    normalized_scope = scope.lower()
    valid_scopes = {"all", "python", "js"}
    if normalized_scope not in valid_scopes:
        raise typer.BadParameter("Scope must be one of: all, python, js")

    try:
        if normalized_scope in {"all", "python"}:
            _run_python_lint(False)
        if normalized_scope in {"all", "js"}:
            _run_js_lint(False)
    except CommandError as error:
        _fail_with_message(error)


@app.command("lint:fix")
def lint_fix(
    scope: str = typer.Option(
        "all",
        "--scope",
        help="Which linters to run (all, python, js).",
        case_sensitive=False,
    ),
) -> None:
    """Fix code quality issues automatically.

    Justification: Separate fix operation into dedicated command for clarity.
    "lint:fix" is explicit: lint and FIX issues.
    """
    normalized_scope = scope.lower()
    valid_scopes = {"all", "python", "js"}
    if normalized_scope not in valid_scopes:
        raise typer.BadParameter("Scope must be one of: all, python, js")

    try:
        if normalized_scope in {"all", "python"}:
            _run_python_lint(True)
        if normalized_scope in {"all", "js"}:
            _run_js_lint(True)
    except CommandError as error:
        _fail_with_message(error)


@app.command("fmt:code")
def fmt_code(
    scope: str = typer.Option(
        "all",
        "--scope",
        help="Which formatters to run (all, python, js).",
        case_sensitive=False,
    ),
) -> None:
    """Format Python and JavaScript code.

    Justification: "fmt" is an abbreviation that's not self-evident. "fmt:code"
    is explicit: we're formatting CODE, not filesystem or something else.
    """
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


@app.command("db:migrate")
def db_migrate() -> None:
    """Apply database migrations (Django and ClickHouse).

    Justification: "migrate" alone doesn't specify what. "db:migrate" is explicit:
    we're migrating the DATABASE, not code or data pipelines.
    """
    try:
        typer.echo(f"{EMOJI_HOG}{EMOJI_SPARKLE} Applying PostHog migrations…")
        _run([str(BIN_DIR / "migrate")])
    except CommandError as error:
        _fail_with_message(error)


@app.command("build:frontend")
def build_frontend(
    scope: str = typer.Option(
        "all",
        "--scope",
        help="Which build targets to run (all, frontend).",
        case_sensitive=False,
    ),
) -> None:
    """Build frontend packages and run TypeScript compilation.

    Justification: "build" could mean backend, containers, artifacts, etc.
    "build:frontend" is explicit: we're building the FRONTEND packages.
    """
    normalized_scope = scope.lower()
    valid_scopes = {"all", "frontend"}
    if normalized_scope not in valid_scopes:
        raise typer.BadParameter("Scope must be one of: all, frontend")

    try:
        if normalized_scope in {"all", "frontend"}:
            _run_frontend_build()
    except CommandError as error:
        _fail_with_message(error)


@app.command("docker:services:up")
def docker_services_up(
    follow: bool = typer.Option(False, "--follow", help="Stream docker-compose logs after startup."),
    rebuild: bool = typer.Option(False, "--rebuild", help="Recreate containers even if they exist."),
) -> None:
    """Start Docker infrastructure services (Postgres, ClickHouse, Redis, Kafka).

    Justification: EXPLICIT "docker:" prefix clarifies this starts Docker containers,
    not local services. Helps developers understand scope and requirements.
    """
    compose_file = str(REPO_ROOT / "docker-compose.dev.yml")
    services = ["db", "clickhouse", "redis", "redis7", "zookeeper", "kafka"]

    try:
        command: list[str] = ["docker", "compose", "-f", compose_file, "up", "-d", *services]
        if rebuild:
            command.insert(command.index("up") + 1, "--force-recreate")
        _run(command, description="(Start infra services)")
        if follow:
            _run(["docker", "compose", "-f", compose_file, "logs", "-f", *services], description="(Follow logs)")
    except CommandError as error:
        _fail_with_message(error)


@app.command("docker:services:down")
def docker_services_down() -> None:
    """Stop Docker infrastructure services.

    Justification: Pair with docker:services:up for symmetry and clarity.
    """
    compose_file = str(REPO_ROOT / "docker-compose.dev.yml")

    try:
        _run(["docker", "compose", "-f", compose_file, "down"], description="(Stop infra services)")
    except CommandError as error:
        _fail_with_message(error)


@app.command("qa:check")
def qa_check(
    linting: bool = typer.Option(True, "--lint/--skip-lint", help="Toggle running Python and JS linters (fast)."),
    build_assets: bool = typer.Option(True, "--build/--skip-build", help="Toggle building the frontend packages."),
) -> None:
    """Run pre-push quality checks: lint + build (~5 min). Tests run separately.

    Justification: "check" was ambiguous with health-check commands. "qa:check"
    is explicit: QA (code quality) check. Tests excluded—they're slow (15+ min).

    Run tests separately in another terminal:
      hogli test:python [selector]
      hogli test:js [selector]
    """
    typer.echo(f"{EMOJI_HOG}{EMOJI_SPARKLE} Running fast quality checks (lint + build)…")
    typer.echo(typer.style("Tip: run tests separately with hogli test:python or hogli test:js", fg=typer.colors.YELLOW))
    try:
        if linting:
            _run_python_lint(False)
            _run_js_lint(False)
        if build_assets:
            _run_frontend_build()
    except CommandError as error:
        _fail_with_message(error)


@app.command(
    "git:worktree",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def git_worktree(ctx: typer.Context) -> None:
    """Manage git worktrees for isolated development.

    Justification: "worktree" is obscure without context. "git:worktree" is explicit:
    we're managing GIT worktrees (isolated branches as directories).
    """
    try:
        _run_phw(list(ctx.args))
    except CommandError as error:
        _fail_with_message(error)


@app.command("products:list")
def products_list(json_output: bool = typer.Option(False, "--json", help="Output as JSON.")) -> None:
    """List available product packages across frontend and backend.

    Justification: Flatten "products list" subcommand into "products:list" for
    consistency with verb:noun pattern. Explicit action (list).
    """

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


def _register_script_commands() -> None:
    """Dynamically register commands from scripts_manifest.yaml.

    YAML keys are CLI names. Supports three types of entries:
    1. bin_script: Delegate to a shell script
    2. steps: Compose multiple hogli commands in sequence
    3. cmd: Execute a direct shell command
    """
    manifest = _load_manifest()
    if not manifest:
        return

    for _category, scripts in manifest.items():
        if not isinstance(scripts, dict):
            continue

        for cli_name, config in scripts.items():
            if not isinstance(config, dict):
                continue

            description = config.get("description", "")
            allow_extra_args = config.get("allow_extra_args", False)

            # Determine command type
            bin_script = config.get("bin_script")
            steps = config.get("steps")  # List of hogli commands to compose
            cmd = config.get("cmd")  # Direct shell command

            if not (bin_script or steps or cmd):
                # No command specified, skip
                continue

            # Handle composition (steps field)
            if steps:

                def make_steps_command(step_list: list, desc: str):
                    def command() -> None:
                        """Composite hogli command."""
                        for step in step_list:
                            typer.echo(f"{EMOJI_HOG}{EMOJI_SPARKLE} Executing: {step}")
                            # Run each step as a hogli subcommand
                            try:
                                _run(["hogli", step])
                            except CommandError as error:
                                _fail_with_message(error)

                    command.__doc__ = desc
                    return command

                app.command(cli_name, help=description)(make_steps_command(steps, description))
                continue

            # Handle direct commands (cmd field)
            if cmd:

                def make_cmd_command(shell_cmd: str, desc: str):
                    def command() -> None:
                        """Direct shell command."""
                        try:
                            _run(shell_cmd.split())
                        except CommandError as error:
                            _fail_with_message(error)

                    command.__doc__ = desc
                    return command

                app.command(cli_name, help=description)(make_cmd_command(cmd, description))
                continue

            # Handle bin_script delegation (original behavior)
            if bin_script:
                script_path = BIN_DIR / bin_script
                if not script_path.exists():
                    continue

                def make_command(name: str, path: Path, desc: str, extra_args: bool):
                    if extra_args:

                        def command(ctx: typer.Context) -> None:
                            """Dynamic command from bin/ script."""
                            _run([str(path), *ctx.args])
                    else:

                        def command() -> None:
                            """Dynamic command from bin/ script."""
                            _run([str(path)])

                    command.__doc__ = desc
                    return command

                context_settings = (
                    {"allow_extra_args": True, "ignore_unknown_options": True} if allow_extra_args else {}
                )
                app.command(
                    cli_name,
                    context_settings=context_settings if context_settings else None,
                    help=description,
                )(make_command(cli_name, script_path, description, allow_extra_args))


# Register all script commands from manifest before app runs
_register_script_commands()


if __name__ == "__main__":
    app()
