import re
from typing import Optional, Union, Any
from collections.abc import Callable
from dataclasses import dataclass
from functools import cmp_to_key


@dataclass
class SemanticVersion:
    major: int
    minor: Optional[int] = None
    patch: Optional[int] = None
    extra: Optional[str] = None


@dataclass
class VersionDiff:
    kind: str
    diff: int


def parse_version(version: str) -> SemanticVersion:
    """Parse a version string into a SemanticVersion object.

    Raises ValueError if the version string is invalid.
    """
    # Split on hyphen to extract extra
    split = version.split("-", 1)
    version_part = split[0]
    extra = split[1] if len(split) > 1 else None

    # Match the version pattern
    match = re.match(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$", version_part)
    if not match:
        raise ValueError(f"Invalid semver string: {version}")

    major_str, minor_str, patch_str = match.groups()

    major = int(major_str)
    minor = int(minor_str) if minor_str is not None else None
    patch = int(patch_str) if patch_str is not None else None

    return SemanticVersion(major=major, minor=minor, patch=patch, extra=extra)


def try_parse_version(version: str) -> Optional[SemanticVersion]:
    """Try to parse a version string, return None if it's invalid."""
    try:
        return parse_version(version)
    except ValueError:
        return None


def diff_versions(a: Union[str, SemanticVersion], b: Union[str, SemanticVersion]) -> Optional[VersionDiff]:
    """Compare two versions and return the difference, or None if they're equal."""
    try:
        pa = parse_version(a) if isinstance(a, str) else a
        pb = parse_version(b) if isinstance(b, str) else b

        if pa.major != pb.major:
            return VersionDiff(kind="major", diff=pa.major - pb.major)

        a_minor = pa.minor or 0
        b_minor = pb.minor or 0
        if a_minor != b_minor:
            return VersionDiff(kind="minor", diff=a_minor - b_minor)

        a_patch = pa.patch or 0
        b_patch = pb.patch or 0
        if a_patch != b_patch:
            return VersionDiff(kind="patch", diff=a_patch - b_patch)

        if pa.extra != pb.extra:
            # not having an extra is treated as a higher version than having an extra
            if pa.extra:
                if pb.extra:
                    # Simple string comparison
                    return VersionDiff(kind="extra", diff=1 if pa.extra > pb.extra else -1)
                return VersionDiff(kind="extra", diff=-1)
            if pb.extra:
                return VersionDiff(kind="extra", diff=1)
            return None

        return None
    except ValueError:
        return None


def compare_version(a: Union[str, SemanticVersion], b: Union[str, SemanticVersion]) -> int:
    """Compare two versions and return the difference as an integer.

    Returns:
        - Positive if a > b
        - Zero if a == b
        - Negative if a < b
    """
    diff = diff_versions(a, b)
    if not diff:
        return 0
    return diff.diff


def lowest_version(versions: list[Union[str, SemanticVersion]]) -> SemanticVersion:
    """Find the lowest version in a list."""
    parsed = [parse_version(v) if isinstance(v, str) else v for v in versions]
    # Use compare_version which properly handles extra components
    return min(parsed, key=cmp_to_key(compare_version))


def highest_version(versions: list[Union[str, SemanticVersion]]) -> SemanticVersion:
    """Find the highest version in a list."""
    parsed = [parse_version(v) if isinstance(v, str) else v for v in versions]
    # Use compare_version which properly handles extra components
    return max(parsed, key=cmp_to_key(compare_version))


def is_equal_version(a: Union[str, SemanticVersion], b: Union[str, SemanticVersion]) -> bool:
    """Check if two versions are equal."""
    return diff_versions(a, b) is None


def version_to_string(version: Union[str, SemanticVersion, Any]) -> str:
    """Convert a version object to a string."""
    if isinstance(version, str):
        return version.lstrip("v")

    if isinstance(version, SemanticVersion):
        version_part = f"{version.major}"
        if version.minor is not None:
            version_part += f".{version.minor}"
            if version.patch is not None:
                version_part += f".{version.patch}"

        if version.extra:
            return f"{version_part}-{version.extra}"

        return version_part

    # Fall back to string conversion for other types
    return str(version).lstrip("v")


def create_version_checker(
    required_version: Union[str, SemanticVersion],
) -> Callable[[Union[str, SemanticVersion]], bool]:
    """Create a function that checks if a version is at least the required version."""

    def check_version(version: Union[str, SemanticVersion]) -> bool:
        diff = diff_versions(version, required_version)
        return diff is None or diff.diff > 0

    return check_version
