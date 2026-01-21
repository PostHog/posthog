"""Tests for intent-based developer environment system."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hogli.devenv.profile import DeveloperProfile, ProfileManager, ProfileOverrides
from hogli.devenv.resolver import Capability, Intent, IntentMap, IntentResolver, Preset, Unit, load_intent_map
from parameterized import parameterized


def create_test_intent_map() -> IntentMap:
    """Create a minimal intent map for testing."""
    return IntentMap(
        version="1.0",
        capabilities={
            "core_infra": Capability(
                name="core_infra",
                description="Core infrastructure",
                units=["docker-compose", "migrate-postgres"],
                requires=[],
            ),
            "event_ingestion": Capability(
                name="event_ingestion",
                description="Event pipeline",
                units=["nodejs", "capture"],
                requires=["core_infra"],
            ),
            "error_symbolication": Capability(
                name="error_symbolication",
                description="Error symbolication",
                units=["cymbal"],
                requires=["event_ingestion"],
            ),
            "replay_storage": Capability(
                name="replay_storage",
                description="Replay storage",
                units=["capture-replay"],
                requires=["event_ingestion"],
            ),
            "flag_evaluation": Capability(
                name="flag_evaluation",
                description="Feature flags",
                units=["feature-flags"],
                requires=["core_infra"],
            ),
        },
        intents={
            "error_tracking": Intent(
                name="error_tracking",
                description="Error tracking",
                capabilities=["event_ingestion", "error_symbolication"],
            ),
            "session_replay": Intent(
                name="session_replay",
                description="Session replay",
                capabilities=["event_ingestion", "replay_storage"],
            ),
            "feature_flags": Intent(
                name="feature_flags",
                description="Feature flags",
                capabilities=["flag_evaluation"],
            ),
            "product_analytics": Intent(
                name="product_analytics",
                description="Product analytics",
                capabilities=["event_ingestion"],
            ),
        },
        units={
            "backend": Unit(name="backend", process="backend", type="python", autostart=True),
            "frontend": Unit(name="frontend", process="frontend", type="node", autostart=True),
            "docker-compose": Unit(name="docker-compose", process="docker-compose", type="docker", autostart=True),
            "migrate-postgres": Unit(name="migrate-postgres", process="migrate-postgres", type="migration"),
            "nodejs": Unit(name="nodejs", process="nodejs", type="node"),
            "capture": Unit(name="capture", process="capture", type="rust"),
            "capture-replay": Unit(name="capture-replay", process="capture-replay", type="rust"),
            "cymbal": Unit(name="cymbal", process="cymbal", type="rust"),
            "feature-flags": Unit(name="feature-flags", process="feature-flags", type="rust"),
            "storybook": Unit(name="storybook", process="storybook", type="node", autostart=False),
        },
        presets={
            "minimal": Preset(
                name="minimal",
                description="Minimal stack",
                intents=["product_analytics"],
            ),
            "full": Preset(
                name="full",
                description="Full stack",
                all_intents=True,
            ),
        },
        always_required=["backend", "frontend", "docker-compose"],
    )


class TestIntentResolver:
    """Test intent resolution logic."""

    @parameterized.expand(
        [
            # (intents, expected_units_subset, description)
            (["error_tracking"], {"cymbal", "nodejs", "capture"}, "error_tracking includes cymbal"),
            (["session_replay"], {"capture-replay", "nodejs", "capture"}, "session_replay includes capture-replay"),
            (["feature_flags"], {"feature-flags"}, "feature_flags includes feature-flags"),
            (["product_analytics"], {"nodejs", "capture"}, "product_analytics includes event pipeline"),
        ]
    )
    def test_resolve_single_intent(self, intents: list[str], expected_subset: set[str], description: str) -> None:
        """Single intent resolves to expected units."""
        intent_map = create_test_intent_map()
        resolver = IntentResolver(intent_map)

        result = resolver.resolve(intents)

        assert expected_subset <= result.units, f"{description}: missing {expected_subset - result.units}"

    def test_resolve_always_includes_required(self) -> None:
        """Resolution always includes always_required units."""
        intent_map = create_test_intent_map()
        resolver = IntentResolver(intent_map)

        result = resolver.resolve(["feature_flags"])

        assert "backend" in result.units
        assert "frontend" in result.units
        assert "docker-compose" in result.units

    def test_resolve_expands_capability_dependencies(self) -> None:
        """Capabilities transitively expand their dependencies."""
        intent_map = create_test_intent_map()
        resolver = IntentResolver(intent_map)

        # error_tracking requires error_symbolication which requires event_ingestion
        # which requires core_infra
        result = resolver.resolve(["error_tracking"])

        # Should include core_infra units (docker-compose, migrate-postgres)
        assert "docker-compose" in result.units
        assert "migrate-postgres" in result.units
        # Should include event_ingestion units
        assert "nodejs" in result.units
        assert "capture" in result.units
        # Should include error_symbolication units
        assert "cymbal" in result.units

    def test_resolve_multiple_intents_unions_units(self) -> None:
        """Multiple intents union their required units."""
        intent_map = create_test_intent_map()
        resolver = IntentResolver(intent_map)

        result = resolver.resolve(["error_tracking", "session_replay"])

        # Should have units from both
        assert "cymbal" in result.units  # error_tracking
        assert "capture-replay" in result.units  # session_replay

    @parameterized.expand(
        [
            (["storybook"], [], {"storybook"}, "include adds units"),
            ([], ["nodejs"], set(), "exclude removes units"),
        ]
    )
    def test_resolve_with_overrides(
        self,
        include: list[str],
        exclude: list[str],
        expected_diff: set[str],
        description: str,
    ) -> None:
        """Overrides modify the resolved units."""
        intent_map = create_test_intent_map()
        resolver = IntentResolver(intent_map)

        result = resolver.resolve(
            ["product_analytics"],
            include_units=include,
            exclude_units=exclude,
        )

        if include:
            assert expected_diff <= result.units, f"{description}"
        if exclude:
            assert not (expected_diff & result.units), f"{description}"

    def test_resolve_unknown_intent_raises(self) -> None:
        """Unknown intent raises ValueError."""
        intent_map = create_test_intent_map()
        resolver = IntentResolver(intent_map)

        with pytest.raises(ValueError, match="Unknown intent"):
            resolver.resolve(["nonexistent"])

    def test_resolve_preset_full(self) -> None:
        """Full preset includes all intents."""
        intent_map = create_test_intent_map()
        resolver = IntentResolver(intent_map)

        result = resolver.resolve_preset("full")

        # Should include units from all intents
        assert "cymbal" in result.units  # error_tracking
        assert "capture-replay" in result.units  # session_replay
        assert "feature-flags" in result.units  # feature_flags

    def test_resolve_preset_minimal(self) -> None:
        """Minimal preset includes only product_analytics."""
        intent_map = create_test_intent_map()
        resolver = IntentResolver(intent_map)

        result = resolver.resolve_preset("minimal")

        # Should have event pipeline but not specialized services
        assert "nodejs" in result.units
        assert "cymbal" not in result.units
        assert "capture-replay" not in result.units

    def test_resolve_unknown_preset_raises(self) -> None:
        """Unknown preset raises ValueError."""
        intent_map = create_test_intent_map()
        resolver = IntentResolver(intent_map)

        with pytest.raises(ValueError, match="Unknown preset"):
            resolver.resolve_preset("nonexistent")

    def test_explain_resolution_includes_all_sections(self) -> None:
        """Explanation includes intents, capabilities, and units."""
        intent_map = create_test_intent_map()
        resolver = IntentResolver(intent_map)

        result = resolver.resolve(["error_tracking"])
        explanation = resolver.explain_resolution(result)

        assert "error_tracking" in explanation
        assert "error_symbolication" in explanation
        assert "cymbal" in explanation


class TestIntentMapLoading:
    """Test intent map loading from YAML."""

    def test_load_real_intent_map(self) -> None:
        """Can load the real intent-map.yaml from the repo."""
        # This test validates the actual file
        intent_map = load_intent_map()

        assert intent_map.version == "1.0"
        assert len(intent_map.intents) > 0
        assert len(intent_map.capabilities) > 0
        assert len(intent_map.units) > 0
        assert len(intent_map.presets) > 0

    def test_real_intent_map_has_key_intents(self) -> None:
        """Real intent map includes key product intents."""
        intent_map = load_intent_map()

        key_intents = ["error_tracking", "session_replay", "product_analytics", "feature_flags"]
        for intent in key_intents:
            assert intent in intent_map.intents, f"Missing intent: {intent}"

    def test_real_intent_map_resolves_without_errors(self) -> None:
        """All intents in real map resolve successfully."""
        intent_map = load_intent_map()
        resolver = IntentResolver(intent_map)

        for intent_name in intent_map.intents:
            # Should not raise
            result = resolver.resolve([intent_name])
            assert len(result.units) > 0


class TestDeveloperProfile:
    """Test developer profile data class."""

    def test_profile_to_dict_minimal(self) -> None:
        """Minimal profile converts to dict cleanly."""
        profile = DeveloperProfile(intents=["error_tracking"])

        data = profile.to_dict()

        assert data["version"] == "1.0"
        assert data["intents"] == ["error_tracking"]
        assert "overrides" not in data  # Empty overrides not included

    def test_profile_to_dict_with_overrides(self) -> None:
        """Profile with overrides includes them."""
        profile = DeveloperProfile(
            intents=["error_tracking"],
            overrides=ProfileOverrides(
                include_units=["storybook"],
                skip_typegen=True,
            ),
        )

        data = profile.to_dict()

        assert data["overrides"]["include_units"] == ["storybook"]
        assert data["overrides"]["skip_typegen"] is True

    def test_profile_from_dict_roundtrip(self) -> None:
        """Profile survives dict roundtrip."""
        original = DeveloperProfile(
            intents=["error_tracking", "session_replay"],
            overrides=ProfileOverrides(
                include_units=["storybook"],
                exclude_units=["dagster"],
                skip_typegen=True,
            ),
        )

        data = original.to_dict()
        restored = DeveloperProfile.from_dict(data)

        assert restored.intents == original.intents
        assert restored.overrides.include_units == original.overrides.include_units
        assert restored.overrides.exclude_units == original.overrides.exclude_units
        assert restored.overrides.skip_typegen == original.overrides.skip_typegen

    def test_profile_with_preset(self) -> None:
        """Profile can use preset instead of intents."""
        profile = DeveloperProfile(preset="minimal")

        data = profile.to_dict()

        assert data["preset"] == "minimal"
        assert "intents" not in data


class TestProfileManager:
    """Test profile persistence."""

    def test_save_and_load_profile(self) -> None:
        """Profile can be saved and loaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(repo_root=Path(tmpdir))
            profile = DeveloperProfile(intents=["error_tracking"])

            manager.save_profile(profile)

            assert manager.profile_exists()
            loaded = manager.load_profile()
            assert loaded is not None
            assert loaded.intents == ["error_tracking"]

    def test_delete_profile(self) -> None:
        """Profile can be deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(repo_root=Path(tmpdir))
            profile = DeveloperProfile(intents=["error_tracking"])

            manager.save_profile(profile)
            assert manager.profile_exists()

            manager.delete_profile()
            assert not manager.profile_exists()

    def test_load_nonexistent_profile(self) -> None:
        """Loading nonexistent profile returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(repo_root=Path(tmpdir))

            loaded = manager.load_profile()

            assert loaded is None

    def test_generated_dir_creation(self) -> None:
        """Generated directory is created on demand."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ProfileManager(repo_root=Path(tmpdir))

            path = manager.ensure_generated_dir()

            assert path.exists()
            assert path.is_dir()
