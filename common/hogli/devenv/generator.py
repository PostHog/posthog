"""Generate process manager configuration from resolved environment.

This module provides an abstract generator interface and an mprocs implementation.
The system is designed to be process-manager agnostic - mprocs is just one output format.
"""

from __future__ import annotations

import os
import re
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel

if TYPE_CHECKING:
    from .registry import ProcessRegistry
    from .resolver import IntentResolver, ResolvedEnvironment


class DevenvConfig(BaseModel):
    """Source configuration for dev environment (what the user selected).

    This gets embedded in the generated mprocs.yaml under _posthog key,
    allowing re-resolution when intent-map changes.
    """

    intents: list[str] = []
    include_units: list[str] = []
    exclude_units: list[str] = []
    skip_autostart: list[str] = []
    enable_autostart: list[str] = []
    log_to_files: bool = False


# Docker compose command building
DOCKER_COMPOSE_BASE = "docker compose -f docker-compose.dev.yml -f docker-compose.profiles.yml"

# VS Code compound generation
VSCODE_UNIT_TO_CONFIGURATION: dict[str, str] = {
    "backend": "Backend",
    "celery-worker": "Celery Threaded Pool",
    "celery-beat": "Celery Beat",
    "frontend": "Frontend",
    "nodejs": "Nodejs Services",
    "temporal-worker": "Temporal Worker",
    "dagster": "Dagster: Debug Dagit UI",
}

VSCODE_CONFIGURATION_ORDER: list[str] = [
    "backend",
    "celery-worker",
    "celery-beat",
    "frontend",
    "nodejs",
    "temporal-worker",
    "dagster",
]

VSCODE_STATIC_COMPOUNDS: list[dict[str, Any]] = [
    {
        "name": "PostHog",
        "configurations": [
            "Backend",
            "Celery Threaded Pool",
            "Celery Beat",
            "Frontend",
            "Nodejs Services",
            "Temporal Worker",
        ],
    },
    {
        "name": "PostHog (no typegen)",
        "configurations": [
            "Backend",
            "Celery Threaded Pool",
            "Celery Beat",
            "Frontend (no typegen)",
            "Nodejs Services",
            "Temporal Worker",
        ],
    },
    {
        "name": "PostHog (https)",
        "configurations": [
            "Backend",
            "Celery Threaded Pool",
            "Celery Beat",
            "Frontend (https)",
            "Nodejs Services",
            "Temporal Worker",
        ],
    },
    {
        "name": "PostHog (local billing)",
        "configurations": [
            "Backend (with local billing)",
            "Celery Threaded Pool",
            "Frontend",
            "Nodejs Services",
            "Temporal Worker",
        ],
    },
]


def build_docker_compose_command(profiles: list[str], action: str = "up -d") -> str:
    """Build docker compose command with profile flags.

    Args:
        profiles: List of docker compose profiles to activate
        action: The docker compose action (e.g., "up -d", "down", "down -v")

    Returns:
        Complete docker compose command string
    """
    if profiles:
        profile_flags = " ".join(f"--profile {p}" for p in profiles)
        return f"{DOCKER_COMPOSE_BASE} {profile_flags} {action}"
    return f"{DOCKER_COMPOSE_BASE} {action}"


class ConfigGenerator(ABC):
    """Abstract generator for process manager configurations."""

    @abstractmethod
    def generate(self, resolved: ResolvedEnvironment, source_config: DevenvConfig | None = None) -> Any:
        """Generate configuration for resolved environment."""
        ...

    @abstractmethod
    def save(self, config: Any, output_path: Path) -> Path:
        """Save configuration to file."""
        ...

    def generate_and_save(
        self, resolved: ResolvedEnvironment, output_path: Path, source_config: DevenvConfig | None = None
    ) -> Path:
        """Generate and save configuration in one step."""
        config = self.generate(resolved, source_config)
        return self.save(config, output_path)


class MprocsConfig(BaseModel):
    """Represents an mprocs.yaml configuration."""

    procs: dict[str, dict[str, Any]]
    mouse_scroll_speed: int = 1
    scrollback: int = 10000
    posthog_config: DevenvConfig | None = None  # embedded source config

    def to_yaml_dict(self) -> dict[str, Any]:
        """Serialize to dict with _posthog first for YAML output."""
        result: dict[str, Any] = {}
        if self.posthog_config:
            result["_posthog"] = self.posthog_config.model_dump(exclude_defaults=True)
        result["procs"] = self.procs
        result["mouse_scroll_speed"] = self.mouse_scroll_speed
        result["scrollback"] = self.scrollback
        return result


class MprocsGenerator(ConfigGenerator):
    """Generates mprocs.yaml configuration from resolved environment."""

    def __init__(self, registry: ProcessRegistry):
        """Initialize generator.

        Args:
            registry: ProcessRegistry to get process configs from
        """
        self.registry = registry

    def generate(self, resolved: ResolvedEnvironment, source_config: DevenvConfig | None = None) -> MprocsConfig:
        """Generate mprocs configuration for resolved environment.

        Args:
            resolved: The resolved environment with required units
            source_config: Optional source config to embed for re-resolution

        Returns:
            MprocsConfig with only the required processes
        """
        procs: dict[str, dict[str, Any]] = {}

        # Info process is always first
        procs["info"] = self._build_info_process(resolved)

        # Iterate in original mprocs.yaml order to preserve ordering
        for name in self.registry.get_processes():
            proc_config = self.registry.get_process_config(name)
            if not proc_config:
                continue

            # Include if: in resolved units, or autostart: false (manual start)
            is_resolved = name in resolved.units
            is_manual_start = proc_config.get("autostart") is False

            if not is_resolved and not is_manual_start:
                continue

            # Copy config to avoid mutating registry's internal state
            proc_config = proc_config.copy()

            # Remove metadata fields - not mprocs config
            proc_config.pop("capability", None)
            proc_config.pop("ask_skip", None)

            # Set autostart: false for skipped processes
            if name in resolved.skip_autostart:
                proc_config["autostart"] = False

            # Enable autostart for processes user opted into (overrides source autostart: false)
            if name in resolved.enable_autostart:
                proc_config.pop("autostart", None)

            # Add startup message for resolved units (not manual-start ones)
            if is_resolved and name not in resolved.skip_autostart:
                reason = resolved.get_unit_reason(name)
                proc_config = self._add_startup_message(proc_config, name, reason)

            # Special handling for docker-compose
            if name == "docker-compose":
                proc_config = self._generate_docker_compose_config(resolved.get_docker_profiles_list())

            # Special handling for nodejs - set capability groups based on resolved nodejs_* capabilities
            if name == "nodejs":
                proc_config = self._add_nodejs_capability_groups(proc_config, resolved)

            # Add logging wrapper if enabled
            if source_config and source_config.log_to_files:
                proc_config = self._add_logging(proc_config, name)

            procs[name] = proc_config

        # Get global settings from registry
        global_settings = self.registry.get_global_settings()

        return MprocsConfig(
            procs=procs,
            mouse_scroll_speed=global_settings.get("mouse_scroll_speed", 1),
            scrollback=global_settings.get("scrollback", 10000),
            posthog_config=source_config,
        )

    def _build_info_process(self, resolved: ResolvedEnvironment) -> dict[str, Any]:
        """Build the info process shell command with environment summary and news.

        News is read at runtime from devenv/news.txt so developers always see the
        latest items without re-running hogli dev:generate.
        """
        process_count = len(resolved.units)
        products = sorted(resolved.intents) if resolved.intents else ["(none)"]

        # ANSI color codes matching PostHog brand
        orange = r"\033[38;2;245;78;0m"  # #F54E00
        blue = r"\033[38;2;29;74;255m"  # #1D4AFF
        gray = r"\033[38;5;245m"
        bold = r"\033[1m"
        reset = r"\033[0m"

        # news.txt sits next to intent-map.yaml in the devenv/ directory, which
        # is at the repo root — the same cwd mprocs launches from.
        news_path = "devenv/news.txt"

        shell = f"""\
echo ''
printf '{orange}{bold}  PostHog Dev Environment{reset}\\n'
printf '{gray}  ─────────────────────────────────────{reset}\\n'
echo ''
if [ -f {news_path} ]; then
    printf '  {orange}{bold}News:{reset}\\n'
    while IFS= read -r line || [ -n "$line" ]; do
        [ -z "$line" ] && continue
        printf '    {gray}·{reset} %s\\n' "$line"
    done < {news_path}
    echo ''
fi
printf '  {bold}Commands:{reset}\\n'
printf '    {blue}hogli dev:setup{reset}    Configure which services run\\n'
printf '    {blue}hogli dev:explain{reset}  Show why each service is running\\n'
echo ''
printf '{gray}  ─────────────────────────────────────{reset}\\n'
printf '  {bold}Products:{reset}  {blue}{", ".join(products)}{reset}\\n'
printf '  {bold}Processes:{reset} {process_count} active\\n'
printf '  {gray}Run {reset}{blue}hogli dev:setup{reset}{gray} to tailor this to your workflow.{reset}\\n'"""
        return {"shell": shell}

    def _add_startup_message(self, proc_config: dict[str, Any], process_name: str, reason: str) -> dict[str, Any]:
        """Add a startup message to a process config.

        Args:
            proc_config: The process configuration dict
            process_name: Name of the process
            reason: Why this process is starting (capability name or "always required")

        Returns:
            Modified process configuration with startup message
        """
        original_shell = proc_config.get("shell", "")
        if not original_shell:
            return proc_config

        # Create a friendly message with config hint
        message = f"echo '▶ {process_name}: {reason} (configure via: hogli dev:setup)' && "

        proc_config["shell"] = message + original_shell
        return proc_config

    def _generate_docker_compose_config(self, profiles: list[str]) -> dict[str, Any]:
        """Generate docker-compose process config with profile flags.

        Args:
            profiles: List of docker compose profiles to activate

        Returns:
            Process configuration dict with modified shell command
        """
        # Build the profile flags (may be empty for minimal stack)
        if profiles:
            message = f"echo '▶ docker-compose: profiles: {', '.join(profiles)} (configure via: hogli dev:setup)' && "
        else:
            message = "echo '▶ docker-compose: core services only (configure via: hogli dev:setup)' && "

        up_cmd = build_docker_compose_command(profiles, "up --pull always -d")
        logs_cmd = build_docker_compose_command(profiles, "logs --tail=0 -f")

        return {
            "shell": f"{message}{up_cmd} && {logs_cmd}",
        }

    def _add_nodejs_capability_groups(
        self, proc_config: dict[str, Any], resolved: ResolvedEnvironment
    ) -> dict[str, Any]:
        """Add NODEJS_CAPABILITY_GROUPS env var based on resolved nodejs_* capabilities.

        Strips 'nodejs_' prefix from capability names to get the group name.
        e.g. nodejs_cdp -> cdp, nodejs_session_replay -> session_replay
        """
        prefix = "nodejs_"
        enabled_groups = [cap.removeprefix(prefix) for cap in resolved.capabilities if cap.startswith(prefix)]

        # If no specific groups are enabled, don't set the env var (use default behavior)
        if not enabled_groups:
            return proc_config

        # Build the env var value
        groups_value = ",".join(enabled_groups)

        # Prepend the env var export to the shell command
        original_shell = proc_config.get("shell", "")
        if original_shell:
            proc_config["shell"] = f"export NODEJS_CAPABILITY_GROUPS='{groups_value}' && {original_shell}"

        return proc_config

    def _add_logging(self, proc_config: dict[str, Any], process_name: str) -> dict[str, Any]:
        """Wrap shell command to log output to /tmp/posthog-{name}.log.

        Args:
            proc_config: The process configuration dict
            process_name: Name of the process (used in log filename)

        Returns:
            Modified process configuration with tee logging
        """
        shell = proc_config.get("shell", "")
        if not shell:
            return proc_config

        log_file = f"/tmp/posthog-{process_name}.log"
        proc_config["shell"] = f"{shell} 2>&1 | tee {log_file}"
        return proc_config

    def save(self, config: MprocsConfig, output_path: Path) -> Path:
        """Save mprocs configuration to YAML file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            # Add header comment for log mode
            if config.posthog_config and config.posthog_config.log_to_files:
                f.write("# Log mode: Output logged to /tmp/posthog-*.log\n")
            yaml.dump(config.to_yaml_dict(), f, default_flow_style=False, sort_keys=False)
        return output_path


def load_devenv_config(mprocs_path: Path) -> DevenvConfig | None:
    """Load DevenvConfig from a generated mprocs.yaml file.

    Args:
        mprocs_path: Path to generated mprocs.yaml

    Returns:
        DevenvConfig if _posthog section exists, None otherwise
    """
    if not mprocs_path.exists():
        return None

    try:
        with open(mprocs_path) as f:
            data = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError):
        return None

    posthog_data = data.get("_posthog")
    if not posthog_data:
        return None

    return DevenvConfig.model_validate(posthog_data)


def get_main_repo_from_worktree() -> Path | None:
    """If in a worktree, return the main repo root. Otherwise None."""
    current = Path.cwd().resolve()
    for parent in [current, *current.parents]:
        git_path = parent / ".git"
        if git_path.is_file():
            # Worktree: .git file contains "gitdir: /path/to/main/.git/worktrees/<name>"
            try:
                content = git_path.read_text().strip()
            except OSError:
                return None
            if content.startswith("gitdir: ") and "worktrees" in content:
                gitdir = Path(content.removeprefix("gitdir: ").strip())
                # Resolve relative paths against .git file's directory
                if not gitdir.is_absolute():
                    gitdir = (git_path.parent / gitdir).resolve()
                return gitdir.parent.parent.parent
        elif git_path.is_dir():
            break  # Regular repo, not a worktree
    return None


def get_generated_mprocs_path() -> Path:
    """Get the default path for generated mprocs config.

    Checks local path first, then main repo if in a worktree.
    """
    override_path = os.getenv("HOGLI_MPROCS_PATH")
    if override_path:
        return Path(override_path)

    current = Path.cwd().resolve()
    local_path = current / ".posthog" / ".generated" / "mprocs.yaml"
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            local_path = parent / ".posthog" / ".generated" / "mprocs.yaml"
            break

    # If local config exists (or is symlink), use it
    if local_path.exists():
        return local_path

    # Check main repo if in a worktree
    main_repo = get_main_repo_from_worktree()
    if main_repo:
        main_path = main_repo / ".posthog" / ".generated" / "mprocs.yaml"
        if main_path.exists():
            # Create local symlink so bin/start (which uses $REPOSITORY_ROOT) finds it
            local_path.parent.mkdir(parents=True, exist_ok=True)
            if local_path.is_symlink():
                local_path.unlink()
            local_path.symlink_to(main_path)
            return main_path

    return local_path


def get_vscode_launch_path() -> Path:
    """Get the VS Code launch.json path for the current repository."""
    current = Path.cwd().resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent / ".vscode" / "launch.json"
    return current / ".vscode" / "launch.json"


def _format_intent_label(intent_name: str) -> str:
    """Format an intent name for display in a VS Code compound."""
    acronym_words = {"ai", "llm", "mcp", "cdp"}
    parts = intent_name.split("_")
    formatted_parts: list[str] = []

    for idx, part in enumerate(parts):
        if part in acronym_words:
            formatted_parts.append(part.upper())
        elif idx == 0:
            formatted_parts.append(part.capitalize())
        else:
            formatted_parts.append(part)

    return " ".join(formatted_parts)


def _build_compound(name: str, configurations: list[str], group: str) -> dict[str, Any]:
    """Build a VS Code compound in a consistent shape."""
    return {
        "name": name,
        "configurations": configurations,
        "stopAll": True,
        "presentation": {"group": group},
    }


def _get_configurations_for_units(units: set[str]) -> list[str]:
    """Map resolved units to ordered VS Code configuration names."""
    return [
        VSCODE_UNIT_TO_CONFIGURATION[unit]
        for unit in VSCODE_CONFIGURATION_ORDER
        if unit in units and unit in VSCODE_UNIT_TO_CONFIGURATION
    ]


def build_vscode_compounds(resolver: IntentResolver) -> list[dict[str, Any]]:
    """Build deterministic VS Code compounds from static presets and intents."""
    compounds = [
        _build_compound(name=compound["name"], configurations=compound["configurations"], group="compound")
        for compound in VSCODE_STATIC_COMPOUNDS
    ]

    for intent_name in resolver.intent_map.intents:
        resolved = resolver.resolve([intent_name])
        configurations = _get_configurations_for_units(resolved.units)
        if not configurations:
            continue

        compounds.append(
            _build_compound(
                name=f"PostHog ({_format_intent_label(intent_name)})",
                configurations=configurations,
                group="intent",
            )
        )

    return compounds


def _find_keyed_array_range(content: str, key: str) -> tuple[int, int] | None:
    """Find the [start, end) character range for an array value by key name."""
    key_match = re.search(rf'"{re.escape(key)}"\s*:\s*\[', content)
    if not key_match:
        return None

    start = key_match.end() - 1  # points to '['
    depth = 0
    in_string = False
    escaped = False

    for idx in range(start, len(content)):
        char = content[idx]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return start, idx + 1

    return None


def regenerate_vscode_launch_config(resolver: IntentResolver, output_path: Path | None = None) -> Path | None:
    """Regenerate .vscode/launch.json compounds from deterministic presets.

    This keeps launch.json stable and committed while still allowing hogli to
    refresh the generated compound list whenever dev commands run.
    """
    launch_path = output_path or get_vscode_launch_path()
    if not launch_path.exists():
        return None

    try:
        raw_content = launch_path.read_text()
    except OSError:
        return None

    compounds_range = _find_keyed_array_range(raw_content, "compounds")
    if not compounds_range:
        return None

    compounds_json_lines = json.dumps(build_vscode_compounds(resolver), indent=4).splitlines()
    indented_compounds_json = "\n".join(
        [compounds_json_lines[0], *[f"    {line}" for line in compounds_json_lines[1:]]]
    )
    start, end = compounds_range
    updated_content = f"{raw_content[:start]}{indented_compounds_json}{raw_content[end:]}"
    updated_content = re.sub(r'("compounds"\s*:)\s+\[', r"\1 [", updated_content, count=1)

    launch_path.parent.mkdir(parents=True, exist_ok=True)
    launch_path.write_text(updated_content if updated_content.endswith("\n") else f"{updated_content}\n")
    return launch_path
