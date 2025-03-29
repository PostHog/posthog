import re
from typing import Optional


def parse_version(version: str) -> tuple[int, int, int]:
    """Parse a version string into a tuple of (major, minor, patch)"""
    # Remove any 'v' prefix
    version = version.lstrip('v')
    # Split on dots and convert to ints, defaulting to 0 if part is missing
    parts = [int(re.sub(r'[^\d].*$', '', part)) for part in (version.split('.') + ['0', '0', '0'])[:3]]
    return tuple(parts)  # type: ignore

def diff_versions(latest: str, current: str) -> Optional[dict]:
    """Compare two version strings and return the difference info"""
    try:
        latest_parts = parse_version(latest)
        current_parts = parse_version(current)

        if latest_parts == current_parts:
            return None

        if latest_parts[0] != current_parts[0]:
            kind = 'major'
            diff = latest_parts[0] - current_parts[0]
        elif latest_parts[1] != current_parts[1]:
            kind = 'minor'
            diff = latest_parts[1] - current_parts[1]
        else:
            kind = 'patch'
            diff = latest_parts[2] - current_parts[2]

        if diff <= 0:
            return None

        return {
            'kind': kind,
            'diff': diff
        }
    except:
        return None

def is_equal_version(v1: str, v2: str) -> bool:
    """Check if two version strings are equal"""
    return parse_version(v1) == parse_version(v2)

def version_to_string(version: str) -> str:
    """Convert version to string format"""
    return str(version).lstrip('v')
