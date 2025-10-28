"""
Phase tracking system for idempotent migration execution.

Tracks the state of each migration phase in phase_tracker.yml:
- Phase ID and name
- Status (pending, in_progress, completed, failed)
- Timestamp
- Error messages
- Files modified
- Operations performed
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml


class PhaseStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PhaseRecord:
    """Record of a single phase execution."""

    id: int
    name: str
    status: PhaseStatus
    timestamp: Optional[str] = None
    error: Optional[str] = None
    files_modified: list[str] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        data = {
            "id": self.id,
            "name": self.name,
            "status": self.status.value if isinstance(self.status, PhaseStatus) else self.status,
        }
        if self.timestamp:
            data["timestamp"] = self.timestamp
        if self.error:
            data["error"] = self.error
        if self.files_modified:
            data["files_modified"] = self.files_modified
        if self.operations:
            data["operations"] = self.operations
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PhaseRecord":
        """Create from dictionary loaded from YAML."""
        status = data["status"]
        if isinstance(status, str):
            status = PhaseStatus(status)

        return cls(
            id=data["id"],
            name=data["name"],
            status=status,
            timestamp=data.get("timestamp"),
            error=data.get("error"),
            files_modified=data.get("files_modified", []),
            operations=data.get("operations", []),
        )


@dataclass
class PhaseTrackerState:
    """Overall state of the migration."""

    product: str
    status: str
    current_phase: Optional[int] = None
    phases: list[PhaseRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        data = {
            "product": self.product,
            "status": self.status,
        }
        if self.current_phase is not None:
            data["current_phase"] = self.current_phase
        if self.phases:
            data["phases"] = [p.to_dict() for p in self.phases]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PhaseTrackerState":
        """Create from dictionary loaded from YAML."""
        phases = [PhaseRecord.from_dict(p) for p in data.get("phases", [])]
        return cls(
            product=data["product"],
            status=data["status"],
            current_phase=data.get("current_phase"),
            phases=phases,
        )


class PhaseTracker:
    """Manages phase tracking state in YAML file."""

    def __init__(self, tracker_path: Path):
        self.tracker_path = tracker_path
        self.state: Optional[PhaseTrackerState] = None

    def load(self) -> PhaseTrackerState:
        """Load phase tracker state from file."""
        if not self.tracker_path.exists():
            # Initialize with empty state
            self.state = PhaseTrackerState(
                product="unknown",
                status="not_started",
                phases=[],
            )
            return self.state

        with open(self.tracker_path) as f:
            data = yaml.safe_load(f)

        self.state = PhaseTrackerState.from_dict(data)
        return self.state

    def save(self) -> None:
        """Save phase tracker state to file."""
        if self.state is None:
            raise ValueError("No state to save. Call load() first.")

        self.tracker_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.tracker_path, "w") as f:
            yaml.dump(
                self.state.to_dict(),
                f,
                default_flow_style=False,
                sort_keys=False,
            )

    def initialize(self, product: str, phase_names: list[str]) -> None:
        """Initialize tracker with phase definitions."""
        phases = [
            PhaseRecord(
                id=i + 1,
                name=name,
                status=PhaseStatus.PENDING,
            )
            for i, name in enumerate(phase_names)
        ]

        self.state = PhaseTrackerState(
            product=product,
            status="in_progress",
            current_phase=1,
            phases=phases,
        )
        self.save()

    def start_phase(self, phase_id: int) -> None:
        """Mark phase as in progress."""
        if self.state is None:
            raise ValueError("State not loaded. Call load() first.")

        phase = self._get_phase(phase_id)
        phase.status = PhaseStatus.IN_PROGRESS
        phase.timestamp = datetime.now().isoformat()
        phase.error = None  # Clear any previous error

        self.state.current_phase = phase_id

        # If overall status was failed, reset to in_progress when retrying
        if self.state.status == "failed":
            self.state.status = "in_progress"

        self.save()

    def complete_phase(
        self,
        phase_id: int,
        files_modified: Optional[list[str]] = None,
        operations: Optional[list[str]] = None,
    ) -> None:
        """Mark phase as completed."""
        if self.state is None:
            raise ValueError("State not loaded. Call load() first.")

        phase = self._get_phase(phase_id)
        phase.status = PhaseStatus.COMPLETED
        phase.timestamp = datetime.now().isoformat()

        if files_modified:
            phase.files_modified = files_modified
        if operations:
            phase.operations = operations

        # Move to next phase if available
        if phase_id < len(self.state.phases):
            self.state.current_phase = phase_id + 1
        else:
            # All phases complete
            self.state.status = "completed"
            self.state.current_phase = None

        self.save()

    def fail_phase(self, phase_id: int, error: str) -> None:
        """Mark phase as failed with error message."""
        if self.state is None:
            raise ValueError("State not loaded. Call load() first.")

        phase = self._get_phase(phase_id)
        phase.status = PhaseStatus.FAILED
        phase.timestamp = datetime.now().isoformat()
        phase.error = error

        self.state.status = "failed"
        self.save()

    def get_current_phase(self) -> Optional[PhaseRecord]:
        """Get the current phase to execute."""
        if self.state is None or self.state.current_phase is None:
            return None

        return self._get_phase(self.state.current_phase)

    def get_next_pending_phase(self) -> Optional[PhaseRecord]:
        """Get the next phase that hasn't been completed."""
        if self.state is None:
            return None

        for phase in self.state.phases:
            if phase.status in (PhaseStatus.PENDING, PhaseStatus.FAILED):
                return phase

        return None

    def is_completed(self) -> bool:
        """Check if all phases are completed."""
        if self.state is None:
            return False

        return all(phase.status == PhaseStatus.COMPLETED for phase in self.state.phases)

    def _get_phase(self, phase_id: int) -> PhaseRecord:
        """Get phase by ID."""
        if self.state is None:
            raise ValueError("State not loaded. Call load() first.")

        for phase in self.state.phases:
            if phase.id == phase_id:
                return phase

        raise ValueError(f"Phase {phase_id} not found")

    def reset(self) -> None:
        """Reset all phases to pending state."""
        if self.state is None:
            raise ValueError("State not loaded. Call load() first.")

        for phase in self.state.phases:
            phase.status = PhaseStatus.PENDING
            phase.timestamp = None
            phase.error = None
            phase.files_modified = []
            phase.operations = []

        self.state.status = "in_progress"
        self.state.current_phase = 1
        self.save()

    def print_status(self) -> None:
        """Print current status to console."""
        if self.state is None:
            print("No state loaded")
            return

        print(f"Product: {self.state.product}")
        print(f"Status: {self.state.status}")
        print(f"Current Phase: {self.state.current_phase}")
        print()
        print("Phases:")
        for phase in self.state.phases:
            status_icon = {
                PhaseStatus.PENDING: "⏳",
                PhaseStatus.IN_PROGRESS: "🔄",
                PhaseStatus.COMPLETED: "✅",
                PhaseStatus.FAILED: "❌",
            }.get(phase.status, "?")

            print(f"  {status_icon} Phase {phase.id}: {phase.name} ({phase.status.value})")

            if phase.timestamp:
                print(f"      Timestamp: {phase.timestamp}")
            if phase.error:
                print(f"      Error: {phase.error}")
            if phase.files_modified:
                print(f"      Files modified: {len(phase.files_modified)}")
            if phase.operations:
                print(f"      Operations: {len(phase.operations)}")
