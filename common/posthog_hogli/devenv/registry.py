"""Process registry abstraction for developer environment.

Provides an abstraction over process definitions, making the intent system
agnostic to the underlying process manager (mprocs, pm2, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ProcessDefinition:
    """A process definition from a process manager config."""

    name: str
    capability: str | None  # None for always_required or unassigned
    shell: str = ""
    config: dict[str, Any] = field(default_factory=dict)  # original config for passthrough


class ProcessRegistry(ABC):
    """Abstract registry of available processes and their capabilities."""

    @abstractmethod
    def get_processes(self) -> dict[str, ProcessDefinition]:
        """Get all process definitions."""
        ...

    @abstractmethod
    def get_capability_units(self, capability: str) -> list[str]:
        """Get process names that provide a capability."""
        ...

    @abstractmethod
    def get_all_capabilities(self) -> set[str]:
        """Get all capabilities declared by processes."""
        ...

    @abstractmethod
    def get_process_config(self, name: str) -> dict[str, Any]:
        """Get the original config for a process (for output generation)."""
        ...

    @abstractmethod
    def get_global_settings(self) -> dict[str, Any]:
        """Get global settings (scrollback, mouse_scroll_speed, etc.)."""
        ...


class MprocsRegistry(ProcessRegistry):
    """Process registry backed by mprocs.yaml."""

    def __init__(self, mprocs_path: Path):
        self.mprocs_path = mprocs_path
        self._data: dict[str, Any] | None = None
        self._processes: dict[str, ProcessDefinition] | None = None

    @property
    def data(self) -> dict[str, Any]:
        """Lazy-load the raw YAML data."""
        if self._data is None:
            with open(self.mprocs_path) as f:
                self._data = yaml.safe_load(f)
        return self._data

    @property
    def processes(self) -> dict[str, ProcessDefinition]:
        """Lazy-load process definitions."""
        if self._processes is None:
            self._processes = self._load_processes()
        return self._processes

    def _load_processes(self) -> dict[str, ProcessDefinition]:
        """Parse mprocs.yaml into ProcessDefinitions."""
        processes: dict[str, ProcessDefinition] = {}

        for name, proc_data in self.data.get("procs", {}).items():
            if not isinstance(proc_data, dict):
                continue

            processes[name] = ProcessDefinition(
                name=name,
                capability=proc_data.get("capability"),
                shell=proc_data.get("shell", ""),
                config=proc_data,
            )

        return processes

    def get_processes(self) -> dict[str, ProcessDefinition]:
        return self.processes

    def get_capability_units(self, capability: str) -> list[str]:
        """Get all process names that declare a specific capability."""
        return [p.name for p in self.processes.values() if p.capability == capability]

    def get_all_capabilities(self) -> set[str]:
        """Get set of all capabilities declared by processes."""
        return {p.capability for p in self.processes.values() if p.capability}

    def get_process_config(self, name: str) -> dict[str, Any]:
        """Get original config dict for a process."""
        proc = self.processes.get(name)
        if proc is not None:
            return proc.config.copy()
        return {}

    def get_global_settings(self) -> dict[str, Any]:
        """Get mprocs global settings (scrollback, mouse_scroll_speed, etc.)."""
        return {k: v for k, v in self.data.items() if k != "procs"}

    def get_ask_skip_processes(self) -> list[str]:
        """Get process names that have ask_skip: true."""
        return [name for name, proc in self.processes.items() if proc.config.get("ask_skip") is True]


def get_default_mprocs_path() -> Path:
    """Get the default path to mprocs.yaml."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        mprocs_path = parent / "bin" / "mprocs.yaml"
        if mprocs_path.exists():
            return mprocs_path

    return Path.cwd() / "bin" / "mprocs.yaml"


def create_mprocs_registry(path: Path | None = None) -> MprocsRegistry:
    """Create an MprocsRegistry with defaults."""
    if path is None:
        path = get_default_mprocs_path()
    return MprocsRegistry(path)
