"""Generate mprocs configuration from resolved environment.

Reads process definitions from the base mprocs.yaml and generates a filtered
configuration with only the required units.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .resolver import IntentMap, ResolvedEnvironment


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

    def __init__(
        self,
        base_config_path: Path,
        intent_map: IntentMap,
    ):
        """Initialize generator.

        Args:
            base_config_path: Path to the full mprocs.yaml to use as template
            intent_map: The intent map with unit definitions
        """
        self.base_config_path = base_config_path
        self.intent_map = intent_map
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
            # Get the process name from intent map
            unit = self.intent_map.units.get(unit_name)
            if unit is None:
                # Custom override unit, try to find in base config
                process_name = unit_name
            else:
                process_name = unit.process

            # Get process definition from base config
            if process_name in self.base_config.procs:
                proc_config = self.base_config.procs[process_name].copy()

                # Handle autostart based on unit definition
                if unit is not None and not unit.autostart:
                    proc_config["autostart"] = False

                procs[process_name] = proc_config
            else:
                # Unit not in base config, might be a special case
                pass

        # Handle typegen specially
        if not skip_typegen and "typegen" in self.base_config.procs:
            procs["typegen"] = self.base_config.procs["typegen"].copy()
        elif skip_typegen and "typegen" in procs:
            del procs["typegen"]

        # Handle docker-compose with profiles
        if "docker-compose" in procs and resolved.docker_profiles:
            procs["docker-compose"] = self._generate_docker_compose_config(resolved.get_docker_profiles_list())

        return MprocsConfig(
            procs=procs,
            mouse_scroll_speed=self.base_config.mouse_scroll_speed,
            scrollback=self.base_config.scrollback,
        )

    def _generate_docker_compose_config(self, profiles: list[str]) -> dict[str, Any]:
        """Generate docker-compose process config with profile flags.

        Args:
            profiles: List of docker compose profiles to activate

        Returns:
            Process configuration dict with modified shell command
        """
        # Build the profile flags
        profile_flags = " ".join(f"--profile {p}" for p in profiles)

        # Build the compose command with profiles overlay
        compose_base = "docker compose -f docker-compose.dev.yml -f docker-compose.profiles.yml"
        up_cmd = f"{compose_base} {profile_flags} up --pull always -d"
        logs_cmd = f"{compose_base} {profile_flags} logs --tail=0 -f"

        return {
            "shell": f"{up_cmd} && {logs_cmd}",
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


def create_generator(
    base_config_path: Path | None = None,
    intent_map: IntentMap | None = None,
) -> MprocsGenerator:
    """Create an mprocs generator with defaults.

    Args:
        base_config_path: Path to base mprocs.yaml, or None for default
        intent_map: IntentMap to use, or None to load default

    Returns:
        Configured MprocsGenerator
    """
    from .resolver import load_intent_map

    if base_config_path is None:
        base_config_path = get_default_base_config_path()

    if intent_map is None:
        intent_map = load_intent_map()

    return MprocsGenerator(base_config_path, intent_map)
