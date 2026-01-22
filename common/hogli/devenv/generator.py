"""Generate mprocs configuration from resolved environment.

Reads process definitions from the base mprocs.yaml and generates a filtered
configuration with only the required units.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .resolver import ResolvedEnvironment


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

    def to_yaml(self, path: Path) -> None:
        """Write configuration to YAML file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, sort_keys=False)

    @classmethod
    def from_yaml(cls, path: Path) -> MprocsConfig:
        """Load configuration from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(
            procs=data.get("procs", {}),
            mouse_scroll_speed=data.get("mouse_scroll_speed", 1),
            scrollback=data.get("scrollback", 10000),
        )


class MprocsGenerator:
    """Generates mprocs configuration from resolved environment."""

    def __init__(self, base_config_path: Path):
        """Initialize generator.

        Args:
            base_config_path: Path to the full mprocs.yaml to use as template
        """
        self.base_config_path = base_config_path
        self._base_config: MprocsConfig | None = None

    @property
    def base_config(self) -> MprocsConfig:
        """Lazy-load the base configuration."""
        if self._base_config is None:
            self._base_config = MprocsConfig.from_yaml(self.base_config_path)
        return self._base_config

    def generate(
        self,
        resolved: ResolvedEnvironment,
        skip_typegen: bool = False,
    ) -> MprocsConfig:
        """Generate mprocs configuration for resolved environment.

        Args:
            resolved: The resolved environment with required units
            skip_typegen: Whether to skip typegen process

        Returns:
            MprocsConfig with only the required processes
        """
        procs: dict[str, dict[str, Any]] = {}

        for unit_name in resolved.units:
            # Unit name = process name (they're always the same)
            if unit_name in self.base_config.procs:
                proc_config = self.base_config.procs[unit_name].copy()

                # Add startup message showing why this process is starting
                reason = resolved.get_unit_reason(unit_name)
                proc_config = self._add_startup_message(proc_config, unit_name, reason)

                procs[unit_name] = proc_config

        # Handle typegen specially
        if not skip_typegen and "typegen" in self.base_config.procs:
            proc_config = self.base_config.procs["typegen"].copy()
            proc_config = self._add_startup_message(proc_config, "typegen", "always required")
            procs["typegen"] = proc_config
        elif skip_typegen and "typegen" in procs:
            del procs["typegen"]

        # Handle docker-compose with profiles overlay
        # Always use the profiles overlay when generating from intents - this ensures
        # optional services (temporal, otel, etc.) don't start unless their profile is requested
        if "docker-compose" in procs:
            procs["docker-compose"] = self._generate_docker_compose_config(resolved.get_docker_profiles_list())

        return MprocsConfig(
            procs=procs,
            mouse_scroll_speed=self.base_config.mouse_scroll_speed,
            scrollback=self.base_config.scrollback,
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
        # The profiles overlay adds profile constraints to optional services.
        # Services without a profile always start; services with profiles only
        # start when their profile is activated.
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

    def generate_and_save(
        self,
        resolved: ResolvedEnvironment,
        output_path: Path,
        skip_typegen: bool = False,
    ) -> Path:
        """Generate and save mprocs configuration.

        Args:
            resolved: The resolved environment
            output_path: Where to save the generated config
            skip_typegen: Whether to skip typegen

        Returns:
            Path to the saved configuration
        """
        config = self.generate(resolved, skip_typegen)
        config.to_yaml(output_path)
        return output_path


def get_default_base_config_path() -> Path:
    """Get the default path to the base mprocs.yaml."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        base_config = parent / "bin" / "mprocs.yaml"
        if base_config.exists():
            return base_config

    return Path.cwd() / "bin" / "mprocs.yaml"


def create_generator(base_config_path: Path | None = None) -> MprocsGenerator:
    """Create an mprocs generator with defaults.

    Args:
        base_config_path: Path to base mprocs.yaml, or None for default

    Returns:
        Configured MprocsGenerator
    """
    if base_config_path is None:
        base_config_path = get_default_base_config_path()

    return MprocsGenerator(base_config_path)
