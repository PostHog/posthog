"""Generate process manager configuration from resolved environment.

This module provides an abstract generator interface and an mprocs implementation.
The system is designed to be process-manager agnostic - mprocs is just one output format.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel

if TYPE_CHECKING:
    from .registry import ProcessRegistry
    from .resolver import ResolvedEnvironment


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
        # Build the compose command with profiles overlay
        compose_base = "docker compose -f docker-compose.dev.yml -f docker-compose.profiles.yml"

        # Build the profile flags (may be empty for minimal stack)
        if profiles:
            profile_flags = " " + " ".join(f"--profile {p}" for p in profiles)
            message = f"echo '▶ docker-compose: profiles: {', '.join(profiles)} (configure via: hogli dev:setup)' && "
        else:
            profile_flags = ""
            message = "echo '▶ docker-compose: core services only (configure via: hogli dev:setup)' && "

        up_cmd = f"{compose_base}{profile_flags} up --pull always -d"
        logs_cmd = f"{compose_base}{profile_flags} logs --tail=0 -f"

        return {
            "shell": f"{message}{up_cmd} && {logs_cmd}",
        }

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


def get_generated_mprocs_path() -> Path:
    """Get the default path for generated mprocs config."""
    # Walk up from cwd to find repo root
    current = Path.cwd().resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent / ".posthog" / ".generated" / "mprocs.yaml"
    return current / ".posthog" / ".generated" / "mprocs.yaml"
