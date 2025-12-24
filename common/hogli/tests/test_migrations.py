"""Tests for migration management - security-critical validation."""

from __future__ import annotations

import pytest

from parameterized import parameterized


class TestPathTraversalValidation:
    """Test path validation prevents directory traversal and injection attacks."""

    @parameterized.expand(
        [
            # Valid cases - standard PostHog apps
            ("posthog", "0001_initial"),
            ("ee", "0952_add_sync_test_branch_two"),
            ("rbac", "0123_some_migration_name"),
            # Valid cases - product apps
            ("web_analytics", "0001_initial"),
            ("data_warehouse", "0042_add_feature"),
            # Valid cases - edge cases for valid patterns
            ("a", "0001_a"),  # Single char app name
            ("app123", "9999_migration_name_with_underscores"),
        ]
    )
    def test_valid_inputs_pass_validation(self, app: str, name: str) -> None:
        """Valid app names and migration names should pass validation."""
        from hogli.migration_utils import validate_migration_path_components

        # Should not raise
        validate_migration_path_components(app, name)

    @parameterized.expand(
        [
            # Path traversal via app name
            ("../etc", "0001_passwd", "app"),
            ("posthog/../../../etc", "0001_test", "app"),
            ("..", "0001_test", "app"),
            ("posthog/../../bad", "0001_test", "app"),
            ("./posthog", "0001_test", "app"),
            # Path traversal via migration name
            ("posthog", "../../../etc/passwd", "migration"),
            ("posthog", "0001_../../bad", "migration"),
            ("posthog", "0001_test/../../../etc", "migration"),
            ("posthog", "./0001_test", "migration"),
        ]
    )
    def test_path_traversal_rejected(self, app: str, name: str, _field: str) -> None:
        """Path traversal attempts should raise ValueError."""
        from hogli.migration_utils import validate_migration_path_components

        with pytest.raises(ValueError):
            validate_migration_path_components(app, name)

    @parameterized.expand(
        [
            # Shell injection via app name
            ("posthog;rm -rf /", "0001_test", "app"),
            ("posthog|whoami", "0001_test", "app"),
            ("posthog`id`", "0001_test", "app"),
            ("posthog$(whoami)", "0001_test", "app"),
            ("posthog&echo", "0001_test", "app"),
            # Shell injection via migration name
            ("posthog", "0001_test;DROP TABLE", "migration"),
            ("posthog", "0001_test|cat /etc/passwd", "migration"),
            ("posthog", "0001_`id`", "migration"),
            ("posthog", "0001_$(whoami)", "migration"),
        ]
    )
    def test_shell_injection_rejected(self, app: str, name: str, _field: str) -> None:
        """Shell metacharacters should raise ValueError."""
        from hogli.migration_utils import validate_migration_path_components

        with pytest.raises(ValueError):
            validate_migration_path_components(app, name)

    @parameterized.expand(
        [
            # Invalid app name formats
            ("", "0001_test", "Empty app name"),
            ("123app", "0001_test", "App starting with number"),
            ("app-name", "0001_test", "App with hyphen"),
            ("app.name", "0001_test", "App with dot"),
            ("app name", "0001_test", "App with space"),
            # Invalid migration name formats
            ("posthog", "", "Empty migration name"),
            ("posthog", "0001", "Missing description after number"),
            ("posthog", "001_test", "Wrong digit count (3)"),
            ("posthog", "00001_test", "Wrong digit count (5)"),
            ("posthog", "test_0001", "Number not at start"),
            ("posthog", "0001-test", "Hyphen instead of underscore"),
            ("posthog", "0001_test.py", "Includes file extension"),
            ("posthog", "0001 test", "Space in name"),
            ("posthog", "0001_Test-Name", "Hyphen in description"),
        ]
    )
    def test_invalid_format_rejected(self, app: str, name: str, _description: str) -> None:
        """Invalid format patterns should raise ValueError."""
        from hogli.migration_utils import validate_migration_path_components

        with pytest.raises(ValueError):
            validate_migration_path_components(app, name)


class TestIsValidMigrationPath:
    """Test the bool-returning validation function."""

    @parameterized.expand(
        [
            # Valid cases
            ("posthog", "0001_initial", True),
            ("ee", "0952_add_feature", True),
            # Invalid cases - path traversal
            ("../etc", "0001_passwd", False),
            ("posthog", "../../../etc/passwd", False),
            # Invalid cases - shell injection
            ("posthog;rm", "0001_test", False),
            ("posthog", "0001_;DROP", False),
            # Invalid cases - format
            ("", "0001_test", False),
            ("posthog", "", False),
            ("123app", "0001_test", False),
            ("posthog", "001_test", False),
        ]
    )
    def test_is_valid_migration_path(self, app: str, name: str, expected: bool) -> None:
        """Test the bool-returning validation function."""
        from hogli.migration_utils import is_valid_migration_path

        result = is_valid_migration_path(app, name)
        assert result is expected


class TestCachePathSecurity:
    """Test that cache path generation is secure."""

    def test_get_cache_path_validates_inputs(self) -> None:
        """get_cache_path should validate before constructing path."""
        from hogli.migration_utils import get_cache_path

        # Valid input should return a path
        path = get_cache_path("posthog", "0001_initial")
        assert "posthog" in str(path)
        assert "0001_initial.py" in str(path)

        # Invalid input should raise
        with pytest.raises(ValueError):
            get_cache_path("../etc", "0001_passwd")

        with pytest.raises(ValueError):
            get_cache_path("posthog", "../../../etc/passwd")

    def test_cache_path_stays_within_cache_dir(self) -> None:
        """Cache path should always be under MIGRATION_CACHE_DIR."""
        from hogli.migration_utils import MIGRATION_CACHE_DIR, get_cache_path

        path = get_cache_path("posthog", "0001_initial")

        # Resolve to absolute and check it's under cache dir
        resolved = path.resolve()
        cache_resolved = MIGRATION_CACHE_DIR.resolve()

        # Use is_relative_to() for proper path boundary checks
        # (startswith can have false positives like /tmp/cacheevil matching /tmp/cache)
        assert resolved.is_relative_to(cache_resolved)


class TestSharedMigrationUtils:
    """Test the shared migration_utils module directly."""

    def test_validate_raises_for_invalid_app(self) -> None:
        """validate_migration_path_components should raise for invalid app."""
        from hogli.migration_utils import validate_migration_path_components

        with pytest.raises(ValueError, match="Invalid app name"):
            validate_migration_path_components("../bad", "0001_test")

    def test_validate_raises_for_invalid_migration(self) -> None:
        """validate_migration_path_components should raise for invalid migration."""
        from hogli.migration_utils import validate_migration_path_components

        with pytest.raises(ValueError, match="Invalid migration name"):
            validate_migration_path_components("posthog", "bad_name")

    def test_is_valid_returns_bool(self) -> None:
        """is_valid_migration_path should return bool without raising."""
        from hogli.migration_utils import is_valid_migration_path

        assert is_valid_migration_path("posthog", "0001_initial") is True
        assert is_valid_migration_path("../etc", "0001_passwd") is False
        assert is_valid_migration_path("posthog", "bad") is False

    def test_get_cached_migration_returns_none_for_invalid(self) -> None:
        """get_cached_migration should return None for invalid inputs."""
        from hogli.migration_utils import get_cached_migration

        # Invalid inputs should return None (not raise)
        assert get_cached_migration("../etc", "0001_passwd") is None
        assert get_cached_migration("posthog", "bad") is None

    def test_cache_migration_file_returns_false_for_invalid(self) -> None:
        """cache_migration_file should return False for invalid inputs."""
        from pathlib import Path

        from hogli.migration_utils import cache_migration_file

        # Invalid inputs should return False (not raise)
        assert cache_migration_file("../etc", "0001_passwd", Path("/fake")) is False
        assert cache_migration_file("posthog", "bad", Path("/fake")) is False
