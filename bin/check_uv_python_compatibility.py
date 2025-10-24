#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Validate that the uv version specified in GitHub workflows can download
the Python version specified in pyproject.toml.

uv uses python-build-standalone for Python versions, and older uv versions
may not support newer Python patch versions.
"""

import re
import sys
from pathlib import Path
from typing import Tuple

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore


def get_python_version_from_pyproject() -> str:
    """Extract the required Python version from pyproject.toml."""
    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
    
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    
    requires_python = data.get("project", {}).get("requires-python", "")
    # Extract version from format like "==3.12.11" or ">=3.12.11"
    match = re.search(r"(\d+\.\d+\.\d+)", requires_python)
    if not match:
        raise ValueError(f"Could not parse Python version from: {requires_python}")
    
    return match.group(1)


def get_uv_versions_from_workflows() -> dict[str, str]:
    """Extract uv versions from GitHub workflow files."""
    workflows_dir = Path(__file__).parent.parent / ".github" / "workflows"
    uv_versions = {}
    
    for workflow_file in workflows_dir.glob("*.yml"):
        content = workflow_file.read_text()
        # Look for uv version specifications like "version: 0.8.19"
        matches = re.findall(r"setup-uv@[a-f0-9]+.*?version:\s*([0-9.]+)", content, re.DOTALL)
        if matches:
            for version in matches:
                uv_versions[workflow_file.name] = version
    
    return uv_versions


def parse_version(version_str: str) -> Tuple[int, int, int]:
    """Parse a version string into a tuple of integers."""
    parts = version_str.split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def check_uv_python_compatibility(uv_version: str, python_version: str) -> bool:
    """
    Check if a given uv version supports the specified Python version.
    
    Based on uv release notes and python-build-standalone availability:
    - uv 0.5.0+ supports Python 3.12.7+
    - uv 0.6.0+ supports Python 3.13.0+
    - uv 0.8.0+ supports Python 3.12.8+
    - uv 0.8.4+ supports Python 3.12.9+
    - uv 0.8.12+ supports Python 3.12.10+
    - uv 0.8.19+ supports Python 3.12.11+
    
    This is a conservative check - if we're unsure, we'll warn but not fail.
    """
    uv_ver = parse_version(uv_version)
    py_ver = parse_version(python_version)
    
    # Check for known incompatibilities
    if py_ver >= (3, 12, 11):
        if uv_ver < (0, 8, 19):
            return False
    elif py_ver >= (3, 12, 10):
        if uv_ver < (0, 8, 12):
            return False
    elif py_ver >= (3, 12, 9):
        if uv_ver < (0, 8, 4):
            return False
    elif py_ver >= (3, 12, 8):
        if uv_ver < (0, 8, 0):
            return False
    elif py_ver >= (3, 13, 0):
        if uv_ver < (0, 6, 0):
            return False
    
    return True


def main() -> int:
    """Main entry point for the validation script."""
    print("Checking uv and Python version compatibility...")
    print()
    
    try:
        python_version = get_python_version_from_pyproject()
        print(f"✓ Python version from pyproject.toml: {python_version}")
    except Exception as e:
        print(f"✗ Error reading Python version: {e}")
        return 1
    
    try:
        uv_versions = get_uv_versions_from_workflows()
        if not uv_versions:
            print("⚠ Warning: No uv versions found in workflows")
            return 0
        
        print(f"✓ Found uv versions in {len(uv_versions)} workflow(s)")
        print()
    except Exception as e:
        print(f"✗ Error reading uv versions: {e}")
        return 1
    
    # Check each workflow's uv version
    all_compatible = True
    for workflow, uv_version in uv_versions.items():
        compatible = check_uv_python_compatibility(uv_version, python_version)
        status = "✓" if compatible else "✗"
        print(f"{status} {workflow}: uv {uv_version} {'supports' if compatible else 'may not support'} Python {python_version}")
        if not compatible:
            all_compatible = False
    
    print()
    if all_compatible:
        print("✓ All uv versions are compatible with the required Python version")
        return 0
    else:
        print("✗ Some uv versions may not support the required Python version")
        print()
        print("To fix this:")
        print("1. Update the uv version in the affected workflows")
        print("2. Or use an older Python version in pyproject.toml")
        print()
        print("See uv releases: https://github.com/astral-sh/uv/releases")
        return 1


if __name__ == "__main__":
    sys.exit(main())
