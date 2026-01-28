"""Intent resolution engine for developer environment.

Resolves developer intents to the minimal set of units (processes) needed.

Resolution algorithm:
1. Intents → Capabilities: Map selected intents to their required capabilities
2. Expand dependencies: Transitively expand capability dependencies
3. Capabilities → Units: Query ProcessRegistry for units that provide each capability
4. Apply overrides: Add/remove units based on developer overrides
5. Add always-required: Add units that are always needed (backend, frontend, etc.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from .registry import ProcessRegistry


@dataclass
class Capability:
    """A capability represents a stable abstraction over units.

    Capabilities don't list their units directly - that mapping is in the
    ProcessRegistry (e.g., mprocs.yaml where processes declare their capability).
    """

    name: str
    description: str
    requires: list[str] = field(default_factory=list)
    docker_profiles: list[str] = field(default_factory=list)


@dataclass
class Intent:
    """An intent represents a product/feature a developer works on."""

    name: str
    description: str
    capabilities: list[str]


@dataclass
class IntentMap:
    """Domain model loaded from intent-map.yaml.

    Contains capabilities (abstractions) and intents (products).
    Does NOT contain unit/process information - that's in the ProcessRegistry.
    """

    version: str
    capabilities: dict[str, Capability]
    intents: dict[str, Intent]
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

        return cls(
            version=data.get("version", "1.0"),
            capabilities=capabilities,
            intents=intents,
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
    unit_provenance: dict[str, str] = field(default_factory=dict)  # unit -> reason
    skip_autostart: set[str] = field(default_factory=set)  # units to include but not auto-start
    enable_autostart: set[str] = field(default_factory=set)  # units to enable autostart (override source)

    def get_unit_list(self) -> list[str]:
        """Get sorted list of units for consistent output."""
        return sorted(self.units)

    def get_docker_profiles_list(self) -> list[str]:
        """Get sorted list of docker profiles for consistent output."""
        return sorted(self.docker_profiles)

    def get_unit_reason(self, unit: str) -> str:
        """Get human-readable reason why a unit is included."""
        return self.unit_provenance.get(unit, "unknown")


class IntentResolver:
    """Resolves developer intents to the minimal set of units needed.

    Requires both an IntentMap (domain model) and a ProcessRegistry (unit definitions).
    """

    def __init__(self, intent_map: IntentMap, registry: ProcessRegistry):
        self.intent_map = intent_map
        self.registry = registry

    def resolve(
        self,
        intents: list[str],
        include_units: list[str] | None = None,
        exclude_units: list[str] | None = None,
        include_capabilities: list[str] | None = None,
        skip_autostart: list[str] | None = None,
        enable_autostart: list[str] | None = None,
    ) -> ResolvedEnvironment:
        """Resolve intents to the minimal set of units.

        Args:
            intents: List of intent names to resolve
            include_units: Additional units to include (overrides)
            exclude_units: Units to exclude (overrides)
            include_capabilities: Additional capabilities to include (for docker profiles, etc.)
            skip_autostart: Units to include but not auto-start
            enable_autostart: Units to enable autostart (override source autostart: false)

        Returns:
            ResolvedEnvironment with the resolved units and metadata
        """
        include_units = include_units or []
        exclude_units = exclude_units or []
        include_capabilities = include_capabilities or []
        skip_autostart = skip_autostart or []
        enable_autostart = enable_autostart or []

        # Track provenance: unit -> reason it was included
        unit_provenance: dict[str, str] = {}

        # 1. Intents → Capabilities (track which intent triggered each capability)
        capabilities = self._intents_to_capabilities(intents)
        capability_to_intent = self._map_capabilities_to_intents(intents)

        # 1b. Add any explicitly included capabilities
        capabilities.update(include_capabilities)
        for cap in include_capabilities:
            if cap not in capability_to_intent:
                capability_to_intent[cap] = "explicitly included"

        # 2. Expand capability dependencies (transitive)
        expanded_capabilities = self._expand_capability_dependencies(capabilities)

        # 3. Capabilities → Units (query registry, with provenance tracking)
        units: set[str] = set()
        for cap_name in expanded_capabilities:
            # Find which intent this capability serves
            intent_reason = capability_to_intent.get(cap_name, cap_name)
            # Get units from registry
            cap_units = self.registry.get_capability_units(cap_name)
            for unit in cap_units:
                if unit not in units:
                    units.add(unit)
                    unit_provenance[unit] = f"needed for {intent_reason}"

        # 4. Capabilities → Docker profiles
        docker_profiles = self._capabilities_to_docker_profiles(expanded_capabilities)

        # 5. Apply include overrides
        for unit in include_units:
            if unit not in units:
                units.add(unit)
                unit_provenance[unit] = "manually included"

        # 6. Add always-required
        for unit in self.intent_map.always_required:
            if unit not in units:
                units.add(unit)
                unit_provenance[unit] = "always required"

        # 7. Apply exclude overrides (after always-required so --without can remove them)
        excluded_set = set(exclude_units)
        units = units - excluded_set
        for unit in excluded_set:
            unit_provenance.pop(unit, None)

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
            unit_provenance=unit_provenance,
            skip_autostart=set(skip_autostart),
            enable_autostart=set(enable_autostart),
        )

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

    def _map_capabilities_to_intents(self, intents: list[str]) -> dict[str, str]:
        """Map capabilities back to the intents that require them.

        Returns:
            Dict mapping capability name to intent name (or comma-separated list if multiple)
        """
        cap_to_intents: dict[str, list[str]] = {}

        for intent_name in intents:
            if intent_name not in self.intent_map.intents:
                continue
            intent = self.intent_map.intents[intent_name]

            # Direct capabilities from this intent
            for cap_name in intent.capabilities:
                if cap_name not in cap_to_intents:
                    cap_to_intents[cap_name] = []
                cap_to_intents[cap_name].append(intent_name)

                # Also track transitive dependencies
                self._add_dependency_mappings(cap_name, intent_name, cap_to_intents)

        # Convert lists to comma-separated strings
        return {cap: ", ".join(sorted(set(intents_list))) for cap, intents_list in cap_to_intents.items()}

    def _add_dependency_mappings(self, cap_name: str, intent_name: str, cap_to_intents: dict[str, list[str]]) -> None:
        """Recursively add capability dependency mappings."""
        if cap_name not in self.intent_map.capabilities:
            return

        capability = self.intent_map.capabilities[cap_name]
        for dep_name in capability.requires:
            if dep_name not in cap_to_intents:
                cap_to_intents[dep_name] = []
            cap_to_intents[dep_name].append(intent_name)
            self._add_dependency_mappings(dep_name, intent_name, cap_to_intents)

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

    def get_all_units(self) -> set[str]:
        """Get all units defined in the registry."""
        return set(self.registry.get_processes().keys())

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
        lines.append("\nProcesses to start:")
        for unit_name in sorted(resolved.units):
            reason = resolved.get_unit_reason(unit_name)
            proc_config = self.registry.get_process_config(unit_name)
            if proc_config.get("autostart") is False:
                lines.append(f"  • {unit_name}: {reason} (manual start)")
            else:
                lines.append(f"  • {unit_name}: {reason}")

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
        intent_map = parent / "devenv" / "intent-map.yaml"
        if intent_map.exists():
            return intent_map

    # Fallback: assume we're in the repo
    return Path.cwd() / "devenv" / "intent-map.yaml"


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
