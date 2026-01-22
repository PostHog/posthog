"""Developer profile management for intent-based dev environment.

Handles persistence and loading of developer-specific environment preferences.
Profiles are stored in .posthog/dev.yaml (gitignored).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ProfileOverrides:
    """Overrides that modify the resolved environment."""

    include_units: list[str] = field(default_factory=list)
    exclude_units: list[str] = field(default_factory=list)
    skip_autostart: list[str] = field(default_factory=list)  # processes to include but not auto-start


@dataclass
class DeveloperProfile:
    """A developer's environment configuration."""

    version: str = "1.0"
    intents: list[str] = field(default_factory=list)
    preset: str | None = None
    overrides: ProfileOverrides = field(default_factory=ProfileOverrides)

    def to_dict(self) -> dict[str, Any]:
        """Convert profile to dictionary for YAML serialization."""
        data: dict[str, Any] = {"version": self.version}

        if self.preset:
            data["preset"] = self.preset
        elif self.intents:
            data["intents"] = self.intents

        # Only include overrides if they have values
        overrides_data: dict[str, Any] = {}
        if self.overrides.include_units:
            overrides_data["include_units"] = self.overrides.include_units
        if self.overrides.exclude_units:
            overrides_data["exclude_units"] = self.overrides.exclude_units
        if self.overrides.skip_autostart:
            overrides_data["skip_autostart"] = self.overrides.skip_autostart

        if overrides_data:
            data["overrides"] = overrides_data

        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeveloperProfile:
        """Create profile from dictionary."""
        overrides_data = data.get("overrides", {})
        overrides = ProfileOverrides(
            include_units=overrides_data.get("include_units", []),
            exclude_units=overrides_data.get("exclude_units", []),
            skip_autostart=overrides_data.get("skip_autostart", []),
        )

        return cls(
            version=data.get("version", "1.0"),
            intents=data.get("intents", []),
            preset=data.get("preset"),
            overrides=overrides,
        )

    @classmethod
    def from_yaml(cls, path: Path) -> DeveloperProfile:
        """Load profile from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    def to_yaml(self, path: Path) -> None:
        """Save profile to YAML file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, sort_keys=False)


class ProfileManager:
    """Manages developer profile persistence."""

    # Default location for developer profile
    PROFILE_DIR = ".posthog"
    PROFILE_FILE = "dev.yaml"
    GENERATED_DIR = ".generated"

    def __init__(self, repo_root: Path | None = None):
        """Initialize profile manager.

        Args:
            repo_root: Path to repository root, or None to auto-detect
        """
        self.repo_root = repo_root or self._find_repo_root()

    @property
    def profile_dir(self) -> Path:
        """Get the profile directory path."""
        return self.repo_root / self.PROFILE_DIR

    @property
    def profile_path(self) -> Path:
        """Get the profile file path."""
        return self.profile_dir / self.PROFILE_FILE

    @property
    def generated_dir(self) -> Path:
        """Get the generated files directory path."""
        return self.profile_dir / self.GENERATED_DIR

    def _find_repo_root(self) -> Path:
        """Find the repository root by looking for .git directory."""
        current = Path.cwd().resolve()
        for parent in [current, *current.parents]:
            if (parent / ".git").exists():
                return parent
        return current

    def profile_exists(self) -> bool:
        """Check if a developer profile exists."""
        return self.profile_path.exists()

    def load_profile(self) -> DeveloperProfile | None:
        """Load the developer profile if it exists.

        Returns:
            DeveloperProfile if exists, None otherwise
        """
        if not self.profile_exists():
            return None

        try:
            return DeveloperProfile.from_yaml(self.profile_path)
        except Exception:
            return None

    def save_profile(self, profile: DeveloperProfile) -> None:
        """Save a developer profile.

        Args:
            profile: Profile to save
        """
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        profile.to_yaml(self.profile_path)

    def delete_profile(self) -> bool:
        """Delete the developer profile if it exists.

        Returns:
            True if profile was deleted, False if it didn't exist
        """
        if self.profile_exists():
            self.profile_path.unlink()
            return True
        return False

    def ensure_generated_dir(self) -> Path:
        """Ensure the generated directory exists and return its path."""
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        return self.generated_dir

    def get_generated_mprocs_path(self) -> Path:
        """Get the path for generated mprocs config."""
        return self.generated_dir / "mprocs.yaml"

    def create_default_profile(self, intents: list[str] | None = None) -> DeveloperProfile:
        """Create a default profile with given intents.

        Args:
            intents: List of intents, defaults to ["product_analytics"]

        Returns:
            New DeveloperProfile
        """
        if intents is None:
            intents = ["product_analytics"]

        return DeveloperProfile(intents=intents)

    def create_preset_profile(self, preset: str) -> DeveloperProfile:
        """Create a profile from a preset.

        Args:
            preset: Name of the preset

        Returns:
            New DeveloperProfile with preset set
        """
        return DeveloperProfile(preset=preset)

    def get_profile_summary(self, profile: DeveloperProfile) -> str:
        """Get a human-readable summary of a profile.

        Args:
            profile: Profile to summarize

        Returns:
            Summary string
        """
        lines = []

        if profile.preset:
            lines.append(f"Preset: {profile.preset}")
        elif profile.intents:
            lines.append(f"Intents: {', '.join(profile.intents)}")
        else:
            lines.append("No intents configured")

        if profile.overrides.include_units:
            lines.append(f"Include: {', '.join(profile.overrides.include_units)}")
        if profile.overrides.exclude_units:
            lines.append(f"Exclude: {', '.join(profile.overrides.exclude_units)}")
        if profile.overrides.skip_autostart:
            lines.append(f"Manual start: {', '.join(profile.overrides.skip_autostart)}")

        return "\n".join(lines)


def get_default_profile_manager() -> ProfileManager:
    """Get the default profile manager instance."""
    return ProfileManager()
