"""Generate process manager configuration from resolved environment.

This module provides an abstract generator interface and an mprocs implementation.
The system is designed to be process-manager agnostic - mprocs is just one output format.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from .registry import ProcessRegistry
    from .resolver import ResolvedEnvironment


class ConfigGenerator(ABC):
    """Abstract generator for process manager configurations."""

    @abstractmethod
    def generate(self, resolved: ResolvedEnvironment) -> Any:
        """Generate configuration for resolved environment."""
        ...

    @abstractmethod
    def save(self, config: Any, output_path: Path) -> Path:
        """Save configuration to file."""
        ...

    def generate_and_save(self, resolved: ResolvedEnvironment, output_path: Path) -> Path:
        """Generate and save configuration in one step."""
        config = self.generate(resolved)
        return self.save(config, output_path)


@dataclass
class MprocsConfig:
    """Represents an mprocs.yaml configuration."""

    procs: dict[str, dict[str, Any]]
    mouse_scroll_speed: int = 1
    scrollback: int = 10000

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        return {
            "procs": self.procs,
            "mouse_scroll_speed": self.mouse_scroll_speed,
            "scrollback": self.scrollback,
        }


class MprocsGenerator(ConfigGenerator):
    """Generates mprocs.yaml configuration from resolved environment."""

    def __init__(self, registry: ProcessRegistry):
        """Initialize generator.

        Args:
            registry: ProcessRegistry to get process configs from
        """
        self.registry = registry

    def generate(self, resolved: ResolvedEnvironment) -> MprocsConfig:
        """Generate mprocs configuration for resolved environment.

        Args:
            resolved: The resolved environment with required units

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

            # Add startup message for resolved units (not manual-start ones)
            if is_resolved and name not in resolved.skip_autostart:
                reason = resolved.get_unit_reason(name)
                proc_config = self._add_startup_message(proc_config, name, reason)

            # Special handling for docker-compose
            if name == "docker-compose":
                proc_config = self._generate_docker_compose_config(resolved.get_docker_profiles_list())

            procs[name] = proc_config

        # Get global settings from registry
        global_settings = self.registry.get_global_settings()

        return MprocsConfig(
            procs=procs,
            mouse_scroll_speed=global_settings.get("mouse_scroll_speed", 1),
            scrollback=global_settings.get("scrollback", 10000),
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

        # Create a friendly message
        message = f"echo '▶ {process_name}: {reason}' && "

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
            message = f"echo '▶ docker-compose: running with profiles: {', '.join(profiles)}' && "
        else:
            profile_flags = ""
            message = "echo '▶ docker-compose: running core services only' && "

        up_cmd = f"{compose_base}{profile_flags} up --pull always -d"
        logs_cmd = f"{compose_base}{profile_flags} logs --tail=0 -f"

        return {
            "shell": f"{message}{up_cmd} && {logs_cmd}",
        }

    def save(self, config: MprocsConfig, output_path: Path) -> Path:
        """Save mprocs configuration to YAML file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            yaml.dump(config.to_dict(), f, default_flow_style=False, sort_keys=False)
        return output_path
