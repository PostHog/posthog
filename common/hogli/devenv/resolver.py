"""Intent resolution engine for developer environment.

Resolves developer intents to the minimal set of units (processes) needed.

Resolution algorithm:
1. Intents → Capabilities: Map selected intents to their required capabilities
2. Expand dependencies: Transitively expand capability dependencies
3. Capabilities → Units: Map expanded capabilities to their units
4. Apply overrides: Add/remove units based on developer overrides
5. Add always-required: Add units that are always needed (backend, frontend, etc.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Capability:
    """A capability represents a stable abstraction over units."""

    name: str
    description: str
    units: list[str]
    requires: list[str] = field(default_factory=list)
    docker_profiles: list[str] = field(default_factory=list)


@dataclass
class Intent:
    """An intent represents a product/feature a developer works on."""

    name: str
    description: str
    capabilities: list[str]


@dataclass
class Unit:
    """A unit represents an mprocs process."""

    name: str
    process: str
    type: str
    checks: list[str] = field(default_factory=list)
    autostart: bool = True


@dataclass
class Preset:
    """A preset is a predefined combination of intents."""

    name: str
    description: str
    intents: list[str] = field(default_factory=list)
    all_intents: bool = False
    include_capabilities: list[str] = field(default_factory=list)


@dataclass
class IntentMap:
    """Complete mapping loaded from intent-map.yaml."""

    version: str
    capabilities: dict[str, Capability]
    intents: dict[str, Intent]
    units: dict[str, Unit]
    presets: dict[str, Preset]
    always_required: list[str]

    @classmethod
    def from_yaml(cls, path: Path) -> IntentMap:
        """Load intent map from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)

        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> IntentMap:
        """Create IntentMap from dictionary."""
        capabilities = {}
        for name, cap_data in data.get("capabilities", {}).items():
            capabilities[name] = Capability(
                name=name,
                description=cap_data.get("description", ""),
                units=cap_data.get("units", []),
                requires=cap_data.get("requires", []),
                docker_profiles=cap_data.get("docker_profiles", []),
            )

        intents = {}
        for name, intent_data in data.get("intents", {}).items():
            intents[name] = Intent(
                name=name,
                description=intent_data.get("description", ""),
                capabilities=intent_data.get("capabilities", []),
            )

        units = {}
        for name, unit_data in data.get("units", {}).items():
            units[name] = Unit(
                name=name,
                process=unit_data.get("process", name),
                type=unit_data.get("type", "unknown"),
                checks=unit_data.get("checks", []),
                autostart=unit_data.get("autostart", True),
            )

        presets = {}
        for name, preset_data in data.get("presets", {}).items():
            presets[name] = Preset(
                name=name,
                description=preset_data.get("description", ""),
                intents=preset_data.get("intents", []),
                all_intents=preset_data.get("all_intents", False),
                include_capabilities=preset_data.get("include_capabilities", []),
            )

        return cls(
            version=data.get("version", "1.0"),
            capabilities=capabilities,
            intents=intents,
            units=units,
            presets=presets,
            always_required=data.get("always_required", []),
        )


@dataclass
class ResolvedEnvironment:
    """Result of resolving intents to units."""

    units: set[str]
    capabilities: set[str]
    intents: set[str]
    docker_profiles: set[str] = field(default_factory=set)
    overrides_applied: dict[str, list[str]] = field(default_factory=dict)

    def get_unit_list(self) -> list[str]:
        """Get sorted list of units for consistent output."""
        return sorted(self.units)

    def get_docker_profiles_list(self) -> list[str]:
        """Get sorted list of docker profiles for consistent output."""
        return sorted(self.docker_profiles)


class IntentResolver:
    """Resolves developer intents to the minimal set of units needed."""

    def __init__(self, intent_map: IntentMap):
        self.intent_map = intent_map

    def resolve(
        self,
        intents: list[str],
        include_units: list[str] | None = None,
        exclude_units: list[str] | None = None,
        include_capabilities: list[str] | None = None,
    ) -> ResolvedEnvironment:
        """Resolve intents to the minimal set of units.

        Args:
            intents: List of intent names to resolve
            include_units: Additional units to include (overrides)
            exclude_units: Units to exclude (overrides)
            include_capabilities: Additional capabilities to include (for docker profiles, etc.)

        Returns:
            ResolvedEnvironment with the resolved units and metadata
        """
        include_units = include_units or []
        exclude_units = exclude_units or []
        include_capabilities = include_capabilities or []

        # 1. Intents → Capabilities
        capabilities = self._intents_to_capabilities(intents)

        # 1b. Add any explicitly included capabilities
        capabilities.update(include_capabilities)

        # 2. Expand capability dependencies (transitive)
        expanded_capabilities = self._expand_capability_dependencies(capabilities)

        # 3. Capabilities → Units
        units = self._capabilities_to_units(expanded_capabilities)

        # 4. Capabilities → Docker profiles
        docker_profiles = self._capabilities_to_docker_profiles(expanded_capabilities)

        # 5. Apply overrides
        units = units | set(include_units)
        units = units - set(exclude_units)

        # 6. Add always-required
        units = units | set(self.intent_map.always_required)

        # Track what overrides were applied
        overrides_applied: dict[str, list[str]] = {}
        if include_units:
            overrides_applied["included"] = include_units
        if exclude_units:
            overrides_applied["excluded"] = exclude_units

        return ResolvedEnvironment(
            units=units,
            capabilities=expanded_capabilities,
            intents=set(intents),
            docker_profiles=docker_profiles,
            overrides_applied=overrides_applied,
        )

    def resolve_preset(
        self,
        preset_name: str,
        include_units: list[str] | None = None,
        exclude_units: list[str] | None = None,
        include_capabilities: list[str] | None = None,
    ) -> ResolvedEnvironment:
        """Resolve a preset to units.

        Args:
            preset_name: Name of the preset to resolve
            include_units: Additional units to include
            exclude_units: Units to exclude
            include_capabilities: Additional capabilities to include

        Returns:
            ResolvedEnvironment with the resolved units

        Raises:
            ValueError: If preset not found
        """
        if preset_name not in self.intent_map.presets:
            available = ", ".join(sorted(self.intent_map.presets.keys()))
            raise ValueError(f"Unknown preset '{preset_name}'. Available: {available}")

        preset = self.intent_map.presets[preset_name]

        if preset.all_intents:
            intents = list(self.intent_map.intents.keys())
        else:
            intents = preset.intents

        # Merge preset's include_capabilities with any additional ones
        all_include_capabilities = list(preset.include_capabilities)
        if include_capabilities:
            all_include_capabilities.extend(include_capabilities)

        return self.resolve(intents, include_units, exclude_units, all_include_capabilities or None)

    def _intents_to_capabilities(self, intents: list[str]) -> set[str]:
        """Map intents to their required capabilities."""
        capabilities: set[str] = set()

        for intent_name in intents:
            if intent_name not in self.intent_map.intents:
                available = ", ".join(sorted(self.intent_map.intents.keys()))
                raise ValueError(f"Unknown intent '{intent_name}'. Available: {available}")

            intent = self.intent_map.intents[intent_name]
            capabilities.update(intent.capabilities)

        return capabilities

    def _expand_capability_dependencies(self, capabilities: set[str]) -> set[str]:
        """Transitively expand capability dependencies."""
        expanded: set[str] = set()
        to_process = list(capabilities)

        while to_process:
            cap_name = to_process.pop()

            if cap_name in expanded:
                continue

            if cap_name not in self.intent_map.capabilities:
                available = ", ".join(sorted(self.intent_map.capabilities.keys()))
                raise ValueError(f"Unknown capability '{cap_name}'. Available: {available}")

            expanded.add(cap_name)
            capability = self.intent_map.capabilities[cap_name]

            # Add dependencies to process
            for dep in capability.requires:
                if dep not in expanded:
                    to_process.append(dep)

        return expanded

    def _capabilities_to_units(self, capabilities: set[str]) -> set[str]:
        """Map capabilities to their units."""
        units: set[str] = set()

        for cap_name in capabilities:
            capability = self.intent_map.capabilities[cap_name]
            units.update(capability.units)

        return units

    def _capabilities_to_docker_profiles(self, capabilities: set[str]) -> set[str]:
        """Map capabilities to their docker profiles."""
        profiles: set[str] = set()

        for cap_name in capabilities:
            capability = self.intent_map.capabilities[cap_name]
            profiles.update(capability.docker_profiles)

        return profiles

    def get_available_intents(self) -> list[tuple[str, str]]:
        """Get list of available intents with descriptions."""
        return [(name, intent.description) for name, intent in sorted(self.intent_map.intents.items())]

    def get_available_presets(self) -> list[tuple[str, str]]:
        """Get list of available presets with descriptions."""
        return [(name, preset.description) for name, preset in sorted(self.intent_map.presets.items())]

    def get_available_units(self) -> list[tuple[str, str]]:
        """Get list of available units with their types."""
        return [(name, unit.type) for name, unit in sorted(self.intent_map.units.items())]

    def explain_resolution(self, resolved: ResolvedEnvironment) -> str:
        """Generate human-readable explanation of resolution."""
        lines = []

        lines.append("Intent Resolution")
        lines.append("=" * 40)

        # Intents
        lines.append("\nSelected intents:")
        for intent_name in sorted(resolved.intents):
            intent = self.intent_map.intents.get(intent_name)
            desc = intent.description if intent else "Unknown"
            lines.append(f"  • {intent_name}: {desc}")

        # Capabilities
        lines.append("\nRequired capabilities:")
        for cap_name in sorted(resolved.capabilities):
            cap = self.intent_map.capabilities.get(cap_name)
            desc = cap.description if cap else "Unknown"
            lines.append(f"  • {cap_name}: {desc}")

        # Docker profiles
        if resolved.docker_profiles:
            lines.append("\nDocker profiles:")
            for profile in sorted(resolved.docker_profiles):
                lines.append(f"  • {profile}")
        else:
            lines.append("\nDocker profiles: (core only)")

        # Units
        lines.append("\nUnits to start:")
        for unit_name in sorted(resolved.units):
            unit = self.intent_map.units.get(unit_name)
            if unit:
                autostart = "auto" if unit.autostart else "manual"
                lines.append(f"  • {unit_name} ({unit.type}, {autostart})")
            else:
                lines.append(f"  • {unit_name} (custom)")

        # Overrides
        if resolved.overrides_applied:
            lines.append("\nOverrides applied:")
            if "included" in resolved.overrides_applied:
                lines.append(f"  + Added: {', '.join(resolved.overrides_applied['included'])}")
            if "excluded" in resolved.overrides_applied:
                lines.append(f"  - Removed: {', '.join(resolved.overrides_applied['excluded'])}")

        return "\n".join(lines)


def get_default_intent_map_path() -> Path:
    """Get the default path to intent-map.yaml."""
    # Walk up from this file to find the repo root
    current = Path(__file__).resolve()
    for parent in current.parents:
        intent_map = parent / "dev" / "intent-map.yaml"
        if intent_map.exists():
            return intent_map

    # Fallback: assume we're in the repo
    return Path.cwd() / "dev" / "intent-map.yaml"


def load_intent_map(path: Path | None = None) -> IntentMap:
    """Load intent map from file.

    Args:
        path: Path to intent-map.yaml, or None to use default

    Returns:
        Loaded IntentMap
    """
    if path is None:
        path = get_default_intent_map_path()

    if not path.exists():
        raise FileNotFoundError(f"Intent map not found: {path}")

    return IntentMap.from_yaml(path)
