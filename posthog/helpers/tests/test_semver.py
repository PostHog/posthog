from typing import Union

import pytest
from posthog.helpers.semver import (
    SemanticVersion,
    parse_version,
    try_parse_version,
    diff_versions,
    is_equal_version,
    version_to_string,
    compare_version,
    lowest_version,
    highest_version,
    create_version_checker,
)


class TestVersionUtils:
    def test_parse_version(self):
        # Test basic version parsing
        assert parse_version("1.2.3") == SemanticVersion(major=1, minor=2, patch=3)

        # Test with v prefix
        assert parse_version("v1.2.3") == SemanticVersion(major=1, minor=2, patch=3)

        # Test with missing components
        assert parse_version("1.2") == SemanticVersion(major=1, minor=2)
        assert parse_version("1") == SemanticVersion(major=1)

        # Test with extra
        assert parse_version("1.2.3-beta") == SemanticVersion(major=1, minor=2, patch=3, extra="beta")
        assert parse_version("1.2.3-alpha.1") == SemanticVersion(major=1, minor=2, patch=3, extra="alpha.1")

        # Test invalid versions
        with pytest.raises(ValueError):
            parse_version("not-a-version")
        with pytest.raises(ValueError):
            parse_version("1.2.a")
        with pytest.raises(ValueError):
            parse_version("1.2.3.4.5")

    def test_try_parse_version(self):
        # Test valid versions
        assert try_parse_version("1.2.3") == SemanticVersion(major=1, minor=2, patch=3)

        # Test invalid versions
        assert try_parse_version("not-a-version") is None
        assert try_parse_version("") is None

    def test_diff_versions(self):
        # Test no difference
        assert diff_versions("1.2.3", "1.2.3") is None
        assert diff_versions("v1.2.3", "1.2.3") is None

        # Test major difference
        result = diff_versions("2.0.0", "1.0.0")
        assert result is not None
        assert result.kind == "major"
        assert result.diff == 1

        # Test major difference with multiple versions
        result = diff_versions("5.0.0", "2.0.0")
        assert result is not None
        assert result.kind == "major"
        assert result.diff == 3

        # Test minor difference
        result = diff_versions("1.3.0", "1.1.0")
        assert result is not None
        assert result.kind == "minor"
        assert result.diff == 2

        # Test patch difference
        result = diff_versions("1.2.5", "1.2.3")
        assert result is not None
        assert result.kind == "patch"
        assert result.diff == 2

        # Test older versions
        result = diff_versions("1.0.0", "2.0.0")
        assert result is not None
        assert result.kind == "major"
        assert result.diff == -1

        result = diff_versions("1.2.0", "1.3.0")
        assert result is not None
        assert result.kind == "minor"
        assert result.diff == -1

        # Test with extra
        result = diff_versions("1.2.3", "1.2.3-beta")
        assert result is not None
        assert result.kind == "extra"
        assert result.diff == 1  # No extra is higher than having an extra

        # Test with complex versions
        result = diff_versions("2.0.0-beta", "1.9.0")
        assert result is not None
        assert result.kind == "major"
        assert result.diff == 1

        # Test with invalid versions
        assert diff_versions("not-a-version", "1.0.0") is None
        assert diff_versions("1.0.0", "also-not-a-version") is None
        assert diff_versions("", "") is None

        # Test with SemanticVersion objects
        sv1 = SemanticVersion(major=2, minor=3, patch=4)
        sv2 = SemanticVersion(major=1, minor=9, patch=0)
        result = diff_versions(sv1, sv2)
        assert result is not None
        assert result.kind == "major"
        assert result.diff == 1

    def test_compare_version(self):
        # Equal versions
        assert compare_version("1.2.3", "1.2.3") == 0

        # Greater than
        assert compare_version("2.0.0", "1.0.0") > 0
        assert compare_version("1.2.0", "1.1.0") > 0
        assert compare_version("1.1.2", "1.1.1") > 0

        # Less than
        assert compare_version("1.0.0", "2.0.0") < 0
        assert compare_version("1.1.0", "1.2.0") < 0
        assert compare_version("1.1.1", "1.1.2") < 0

    def test_lowest_version(self):
        versions: list[Union[str, SemanticVersion]] = ["1.2.3", "2.0.0", "1.1.0", "1.5.2"]
        assert lowest_version(versions) == SemanticVersion(major=1, minor=1, patch=0)

        # Test with SemanticVersion objects
        versions = [
            SemanticVersion(major=1, minor=2, patch=3),
            SemanticVersion(major=2, minor=0, patch=0),
            SemanticVersion(major=1, minor=1, patch=0),
        ]
        assert lowest_version(versions) == SemanticVersion(major=1, minor=1, patch=0)

        # Test with extra
        versions = ["1.2.3", "1.2.3-beta", "1.2.3-alpha"]
        assert lowest_version(versions) == SemanticVersion(major=1, minor=2, patch=3, extra="alpha")

    def test_highest_version(self):
        versions: list[Union[str, SemanticVersion]] = ["1.2.3", "2.0.0", "1.1.0", "1.5.2"]
        assert highest_version(versions) == SemanticVersion(major=2, minor=0, patch=0)

        # Test with SemanticVersion objects
        versions = [
            SemanticVersion(major=1, minor=2, patch=3),
            SemanticVersion(major=2, minor=0, patch=0),
            SemanticVersion(major=1, minor=1, patch=0),
        ]
        assert highest_version(versions) == SemanticVersion(major=2, minor=0, patch=0)

        # Test with extra
        versions = ["1.2.3", "1.2.3-beta", "1.2.3-alpha"]
        assert highest_version(versions) == SemanticVersion(major=1, minor=2, patch=3)

    def test_is_equal_version(self):
        # Test equal versions
        assert is_equal_version("1.2.3", "1.2.3") is True
        assert is_equal_version("v1.2.3", "1.2.3") is True

        # Test with v prefix
        assert is_equal_version("v1.2.3", "v1.2.3") is True

        # Test different formats but same version numbers
        assert is_equal_version("1.2", "1.2.0") is True
        assert is_equal_version("1", "1.0.0") is True

        # Test with extra
        assert is_equal_version("1.2.3", "1.2.3-beta") is False

        # Test unequal versions
        assert is_equal_version("1.2.3", "1.2.4") is False
        assert is_equal_version("1.2.3", "1.3.3") is False
        assert is_equal_version("1.2.3", "2.2.3") is False

        # Test with SemanticVersion objects
        sv1 = SemanticVersion(major=1, minor=2, patch=3)
        sv2 = SemanticVersion(major=1, minor=2, patch=3)
        sv3 = SemanticVersion(major=1, minor=2, patch=4)
        assert is_equal_version(sv1, sv2) is True
        assert is_equal_version(sv1, sv3) is False

    def test_version_to_string(self):
        # Test basic string conversion
        assert version_to_string("1.2.3") == "1.2.3"

        # Test with v prefix
        assert version_to_string("v1.2.3") == "1.2.3"

        # Test with SemanticVersion objects
        sv1 = SemanticVersion(major=1, minor=2, patch=3)
        assert version_to_string(sv1) == "1.2.3"

        sv2 = SemanticVersion(major=1)
        assert version_to_string(sv2) == "1"

        sv3 = SemanticVersion(major=1, minor=2)
        assert version_to_string(sv3) == "1.2"

        # Test with extra
        sv4 = SemanticVersion(major=1, minor=2, patch=3, extra="beta")
        assert version_to_string(sv4) == "1.2.3-beta"

        # Test with integer
        assert version_to_string(123) == "123"

        # Test with None - should not raise exception
        assert isinstance(version_to_string(None), str)

    def test_create_version_checker(self):
        # Create version checker for 1.2.0
        check_version = create_version_checker("1.2.0")

        # Test higher versions
        assert check_version("1.2.1") is True
        assert check_version("1.3.0") is True
        assert check_version("2.0.0") is True

        # Test same version
        assert check_version("1.2.0") is True

        # Test lower versions
        assert check_version("1.1.9") is False
        assert check_version("1.1.0") is False
        assert check_version("0.9.0") is False

        # Test with SemanticVersion objects
        sv1 = SemanticVersion(major=1, minor=3, patch=0)
        assert check_version(sv1) is True

        sv2 = SemanticVersion(major=1, minor=1, patch=0)
        assert check_version(sv2) is False
