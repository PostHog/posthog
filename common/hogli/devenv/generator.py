"""Generate process manager configuration from resolved environment.

This module provides an abstract generator interface and an mprocs implementation.
The system is designed to be process-manager agnostic - mprocs is just one output format.
"""

from __future__ import annotations

import os
import re
import json
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel

if TYPE_CHECKING:
    from .registry import ProcessDefinition, ProcessRegistry
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
        self.registry = registry

    def generate(self, resolved: ResolvedEnvironment, source_config: DevenvConfig | None = None) -> MprocsConfig:
        """Generate mprocs configuration for resolved environment."""
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
            proc_config.pop("vscode", None)

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

            # Special handling for backend - wire up personhog env vars when capability is active
            if name == "backend":
                proc_config = self._add_personhog_env(proc_config, resolved)

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
        """Add a startup message to a process config."""
        original_shell = proc_config.get("shell", "")
        if not original_shell:
            return proc_config

        message = f"echo '▶ {process_name}: {reason} (configure via: hogli dev:setup)' && "
        proc_config["shell"] = message + original_shell
        return proc_config

    def _generate_docker_compose_config(self, profiles: list[str]) -> dict[str, Any]:
        """Generate docker-compose process config with profile flags."""
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
        """Add NODEJS_CAPABILITY_GROUPS env var based on resolved nodejs_* capabilities."""
        prefix = "nodejs_"
        enabled_groups = [cap.removeprefix(prefix) for cap in resolved.capabilities if cap.startswith(prefix)]

        if not enabled_groups:
            return proc_config

        groups_value = ",".join(enabled_groups)
        original_shell = proc_config.get("shell", "")
        if original_shell:
            proc_config["shell"] = f"export NODEJS_CAPABILITY_GROUPS='{groups_value}' && {original_shell}"

        return proc_config

    def _add_personhog_env(self, proc_config: dict[str, Any], resolved: ResolvedEnvironment) -> dict[str, Any]:
        """Add PERSONHOG_* env vars to backend when personhog capability is active."""
        if "personhog" not in resolved.capabilities:
            return proc_config

        original_shell = proc_config.get("shell", "")
        if original_shell:
            env_exports = (
                "export PERSONHOG_ADDR='127.0.0.1:50052' PERSONHOG_ENABLED='true' PERSONHOG_ROLLOUT_PERCENTAGE='100'"
            )
            proc_config["shell"] = f"{env_exports} && {original_shell}"

        return proc_config

    def _add_logging(self, proc_config: dict[str, Any], process_name: str) -> dict[str, Any]:
        """Wrap shell command to log output to /tmp/posthog-{name}.log."""
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
            if config.posthog_config and config.posthog_config.log_to_files:
                f.write("# Log mode: Output logged to /tmp/posthog-*.log\n")
            yaml.dump(config.to_yaml_dict(), f, default_flow_style=False, sort_keys=False)
        return output_path


def load_devenv_config(mprocs_path: Path) -> DevenvConfig | None:
    """Load DevenvConfig from a generated mprocs.yaml file."""
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
            try:
                content = git_path.read_text().strip()
            except OSError:
                return None
            if content.startswith("gitdir: ") and "worktrees" in content:
                gitdir = Path(content.removeprefix("gitdir: ").strip())
                if not gitdir.is_absolute():
                    gitdir = (git_path.parent / gitdir).resolve()
                return gitdir.parent.parent.parent
        elif git_path.is_dir():
            break
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

    if local_path.exists():
        return local_path

    main_repo = get_main_repo_from_worktree()
    if main_repo:
        main_path = main_repo / ".posthog" / ".generated" / "mprocs.yaml"
        if main_path.exists():
            local_path.parent.mkdir(parents=True, exist_ok=True)
            if local_path.is_symlink():
                local_path.unlink()
            local_path.symlink_to(main_path)
            return main_path

    return local_path


def _find_repo_root() -> Path:
    """Walk up from cwd to find the repo root (.git directory)."""
    current = Path.cwd().resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return current


def get_vscode_launch_path() -> Path:
    """Get the VS Code launch.json path for the current repository."""
    return _find_repo_root() / ".vscode" / "launch.json"


def get_vscode_launch_template_path() -> Path:
    """Get the VS Code launch.templ.json path for the current repository."""
    return _find_repo_root() / ".vscode" / "launch.templ.json"


# ---------------------------------------------------------------------------
# VS Code launch.json generation
#
# Every resolved unit gets a launch config. Processes with a vscode block in
# mprocs.yaml get an augmented config (debugpy, custom args, etc.). Processes
# without one get a simple node-terminal config running the shell command.
# ---------------------------------------------------------------------------


def _get_display_name(proc: ProcessDefinition) -> str:
    """Get the VS Code display name for a process.

    Reads vscode.name if present, otherwise title-cases the process name.
    """
    if isinstance(proc.vscode_config, dict) and "name" in proc.vscode_config:
        return proc.vscode_config["name"]
    return proc.name.replace("-", " ").title()


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


def _build_debugpy_config(name: str, vscode: dict[str, Any], debugpy_env: dict[str, str]) -> dict[str, Any]:
    """Build a debugpy launch configuration from mprocs.yaml vscode metadata."""
    env = {**debugpy_env}
    if vscode.get("env"):
        env.update(vscode["env"])

    config: dict[str, Any] = {
        "_hogli": True,
        "name": name,
        "consoleName": name,
        "type": "debugpy",
        "request": "launch",
    }

    if "program" in vscode:
        config["program"] = f"${{workspaceFolder}}/{vscode['program']}"
    if "module" in vscode:
        config["module"] = vscode["module"]
    if "args" in vscode:
        config["args"] = vscode["args"]
    if vscode.get("django"):
        config["django"] = True
    if "justMyCode" in vscode:
        config["justMyCode"] = vscode["justMyCode"]
    if vscode.get("autoReload"):
        config["autoReload"] = {"enable": True, "include": ["posthog/**/*.py"]}
    if vscode.get("subProcess"):
        config["subProcess"] = True

    config["console"] = "integratedTerminal"
    config["cwd"] = "${workspaceFolder}"
    config["env"] = env
    config["envFile"] = "${workspaceFolder}/.env"
    config["presentation"] = {"group": "main", "hidden": True}

    return config


def _wrap_command_with_flox(command: str) -> str:
    """Wrap a shell command so it runs inside flox activate, with fallback."""
    escaped = command.replace("'", "'\\''")
    return f"command -v flox >/dev/null 2>&1 && flox activate -- bash -c '{escaped}' || {command}"


def _build_node_terminal_config(
    name: str,
    command: str,
    vscode: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a node-terminal launch configuration."""
    config: dict[str, Any] = {
        "_hogli": True,
        "name": name,
        "type": "node-terminal",
        "request": "launch",
        "command": _wrap_command_with_flox(command),
        "cwd": "${workspaceFolder}",
    }

    if vscode and vscode.get("skipFiles"):
        config["skipFiles"] = vscode["skipFiles"]

    merged_env: dict[str, str] = {}
    if env:
        merged_env.update(env)
    if vscode and vscode.get("env"):
        merged_env.update(vscode["env"])
    if merged_env:
        config["env"] = merged_env

    config["presentation"] = {"group": "main", "hidden": True}

    return config


def build_vscode_configurations(
    resolved: ResolvedEnvironment,
    registry: ProcessRegistry,
) -> list[dict[str, Any]]:
    """Build VS Code launch configurations for all resolved units.

    Every resolved unit gets a config. Processes with a vscode block get an
    augmented config (debugpy, node-terminal with debug settings). Processes
    without one get a simple node-terminal config running the shell command.
    """
    defaults = registry.get_vscode_defaults()
    debugpy_env = defaults.get("debugpy_env", {})
    nodejs_env = defaults.get("nodejs_env", {})

    configurations: list[dict[str, Any]] = []
    processes = registry.get_processes()

    # Iterate in YAML declaration order (dict ordering is stable)
    for name, proc in processes.items():
        if name not in resolved.units:
            continue

        # vscode: false means explicitly excluded from VS Code
        if proc.vscode_config is False:
            continue

        display_name = _get_display_name(proc)
        vscode = proc.vscode_config

        if isinstance(vscode, dict) and vscode.get("type") == "debugpy":
            config = _build_debugpy_config(display_name, vscode, debugpy_env)

        elif isinstance(vscode, dict) and vscode.get("type") == "node-terminal":
            command = vscode.get("command", proc.shell)
            config = _build_node_terminal_config(display_name, command, vscode)

        else:
            # Default: node-terminal running the shell command
            config = _build_node_terminal_config(display_name, proc.shell)

        # Inject nodejs-specific env and NODEJS_CAPABILITY_GROUPS
        if name == "nodejs":
            config.setdefault("env", {}).update(nodejs_env)
            config["envFile"] = "${workspaceFolder}/.env"
            prefix = "nodejs_"
            groups = [cap.removeprefix(prefix) for cap in sorted(resolved.capabilities) if cap.startswith(prefix)]
            if groups:
                config["env"]["NODEJS_CAPABILITY_GROUPS"] = ",".join(groups)

        # Merge process-level env from mprocs.yaml (e.g. llm-gateway)
        proc_env = proc.config.get("env")
        if proc_env:
            config.setdefault("env", {}).update(proc_env)

        configurations.append(config)

    return configurations


def _build_compound(name: str, configurations: list[str], group: str) -> dict[str, Any]:
    """Build a VS Code compound in a consistent shape."""
    return {
        "name": name,
        "configurations": configurations,
        "stopAll": True,
        "presentation": {"group": group},
    }


def _get_config_names_for_units(units: set[str], registry: ProcessRegistry) -> list[str]:
    """Map resolved units to display names in YAML order, excluding vscode: false."""
    return [
        _get_display_name(proc)
        for name, proc in registry.get_processes().items()
        if name in units and proc.vscode_config is not False
    ]


def build_vscode_compounds(
    resolver: IntentResolver,
    resolved: ResolvedEnvironment,
    registry: ProcessRegistry,
) -> list[dict[str, Any]]:
    """Build VS Code compounds from resolved intents.

    Creates a main "PostHog" compound from all resolved units, plus per-intent
    compounds when 2+ intents are selected. Identical config sets are deduplicated.
    """
    main_configs = _get_config_names_for_units(resolved.units, registry)
    main_key = tuple(main_configs)

    intent_labels = [_format_intent_label(name) for name in sorted(resolved.intents)]
    main_name = f"PostHog ({', '.join(intent_labels)})" if intent_labels else "PostHog"
    compounds = [_build_compound(main_name, main_configs, "main")]

    # Per-intent compounds — only useful when multiple intents are selected
    if len(resolved.intents) >= 2:
        config_to_intents: dict[tuple[str, ...], list[str]] = {}
        for intent_name in resolved.intents:
            intent_resolved = resolver.resolve([intent_name])
            configs = tuple(_get_config_names_for_units(intent_resolved.units, registry))
            if not configs or configs == main_key:
                continue
            config_to_intents.setdefault(configs, []).append(intent_name)

        for configs, intent_names in config_to_intents.items():
            labels = [_format_intent_label(name) for name in sorted(intent_names)]
            compound_name = f"PostHog ({', '.join(labels)})"
            compounds.append(_build_compound(compound_name, list(configs), "intent"))

    return compounds


# ---------------------------------------------------------------------------
# launch.json manipulation
# ---------------------------------------------------------------------------


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


def _indent_json_array(data: list[Any], base_indent: str = "    ") -> str:
    """Serialize a JSON array with consistent indentation for launch.json."""
    lines = json.dumps(data, indent=4).splitlines()
    return "\n".join([lines[0], *[f"{base_indent}{line}" for line in lines[1:]]])


def _replace_keyed_array(content: str, key: str, new_data: list[Any]) -> str | None:
    """Replace a JSON array value by key name, preserving surrounding content."""
    array_range = _find_keyed_array_range(content, key)
    if not array_range:
        return None

    start, end = array_range
    new_json = _indent_json_array(new_data)
    content = f"{content[:start]}{new_json}{content[end:]}"
    return re.sub(rf'("{re.escape(key)}"\s*:)\s+\[', rf"\1 [", content, count=1)


def regenerate_vscode_launch_config(
    resolver: IntentResolver,
    resolved: ResolvedEnvironment,
    registry: ProcessRegistry,
    output_path: Path | None = None,
) -> Path:
    """Regenerate .vscode/launch.json from resolved intent configuration.

    Creates launch.json from the template if it doesn't exist yet.
    Generated configs (_hogli marker) are replaced; manual configs are preserved.
    """
    launch_path = output_path or get_vscode_launch_path()

    # Bootstrap from template if launch.json doesn't exist
    if not launch_path.exists():
        template_path = get_vscode_launch_template_path()
        launch_path.parent.mkdir(parents=True, exist_ok=True)
        if template_path.exists():
            shutil.copy2(template_path, launch_path)
        else:
            launch_path.write_text(
                json.dumps({"version": "0.2.0", "configurations": [], "inputs": [], "compounds": []}, indent=4)
            )

    try:
        content = launch_path.read_text()
    except OSError:
        return launch_path

    # Build new generated configurations
    new_configs = build_vscode_configurations(resolved, registry)
    new_config_names = {c["name"] for c in new_configs}

    superseded: set[str] = set(registry.get_vscode_defaults().get("superseded", []))

    configs_range = _find_keyed_array_range(content, "configurations")
    if configs_range:
        start, end = configs_range
        try:
            existing_configs = json.loads(content[start:end])
        except json.JSONDecodeError:
            existing_configs = []

        # Keep manual configs: no _hogli marker, name not colliding with
        # generated, and not in the superseded set
        manual_configs = [
            c
            for c in existing_configs
            if not c.get("_hogli") and c.get("name") not in new_config_names and c.get("name") not in superseded
        ]

        merged = new_configs + manual_configs
        content = _replace_keyed_array(content, "configurations", merged) or content

    # Build compounds from intent resolution
    compounds = build_vscode_compounds(resolver, resolved, registry)
    content = _replace_keyed_array(content, "compounds", compounds) or content

    launch_path.write_text(content if content.endswith("\n") else f"{content}\n")
    return launch_path
