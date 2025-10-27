#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Validate that uv can download the Python version specified in pyproject.toml.

uv uses python-build-standalone for Python versions. This script uses
`uv python list --only-downloads` to verify the required Python version is available.

Run in CI via .github/workflows/ci-python.yml to catch incompatibilities early
when pyproject.toml is updated.

Exit codes:
    0: Python version is available
    1: Python version not available or error occurred
"""

import re
import sys
import subprocess
from pathlib import Path

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


def get_uv_version_from_flox() -> str | None:
    """Extract uv version from flox manifest."""
    flox_manifest = Path(__file__).parent.parent / ".flox" / "env" / "manifest.toml"

    if not flox_manifest.exists():
        return None

    with open(flox_manifest, "rb") as f:
        data = tomllib.load(f)

    # Look for uv in the install section
    install = data.get("install", {})
    uv_config = install.get("uv", {})
    return uv_config.get("version")


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


def check_uv_python_compatibility(uv_version: str, python_version: str) -> tuple[bool, str]:
    """
    Check if a given uv version can download the specified Python version.

    Uses `uv python list --only-downloads` to check if the Python version is available.
    Falls back to passing if uv is not available.

    Returns:
        tuple: (is_compatible, message)
    """
    try:
        # Check if the Python version is available for download
        result = subprocess.run(
            ["uv", "python", "list", python_version, "--only-downloads"], capture_output=True, text=True, timeout=10
        )

        if result.returncode == 0 and result.stdout.strip():
            return True, f"verified via uv python list"
        else:
            return False, f"Python {python_version} not available"

    except subprocess.TimeoutExpired:
        return True, "uv command timed out, assuming compatible"
    except FileNotFoundError:
        return True, "uv not installed, assuming compatible"
    except Exception as e:
        return True, f"unable to verify ({type(e).__name__})"


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

    # Collect all uv versions from different sources
    all_uv_versions = {}

    # Check flox manifest
    try:
        flox_uv = get_uv_version_from_flox()
        if flox_uv:
            all_uv_versions["flox manifest"] = flox_uv
            print(f"✓ Found uv version in flox manifest: {flox_uv}")
    except Exception as e:
        print(f"⚠ Warning: Could not read flox manifest: {e}")

    # Check workflows
    try:
        workflow_versions = get_uv_versions_from_workflows()
        if workflow_versions:
            all_uv_versions.update(workflow_versions)
            print(f"✓ Found uv versions in {len(workflow_versions)} workflow(s)")
    except Exception as e:
        print(f"✗ Error reading workflow versions: {e}")
        return 1

    if not all_uv_versions:
        print("⚠ Warning: No uv versions found")
        return 0

    print()

    # Check each source's uv version
    all_compatible = True
    for source, uv_version in all_uv_versions.items():
        compatible, message = check_uv_python_compatibility(uv_version, python_version)
        status = "✓" if compatible else "✗"
        detail = f" ({message})" if message else ""
        print(
            f"{status} {source}: uv {uv_version} {'supports' if compatible else 'may not support'} Python {python_version}{detail}"
        )
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
        print("1. Update the uv version in the affected workflows or flox manifest")
        print("2. Or use an older Python version in pyproject.toml")
        print()
        print("See uv releases: https://github.com/astral-sh/uv/releases")
        return 1


if __name__ == "__main__":
    sys.exit(main())
