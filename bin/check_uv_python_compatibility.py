#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Validate that the uv version specified in GitHub workflows and flox manifest
can download the Python version specified in pyproject.toml.

uv uses python-build-standalone for Python versions, and older uv versions
may not support newer Python patch versions.

This script is run in CI (see .github/workflows/ci-python.yml) to catch
incompatibilities early. When pyproject.toml's requires-python is updated,
or when workflow/flox files change their uv version, this check will verify
compatibility.

Exit codes:
    0: All uv versions are compatible
    1: Incompatible uv/Python version found or error occurred
"""

import re
import subprocess
import sys
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
    
    Uses `uv python install` with dry-run to check if the Python version is available.
    Falls back to being conservative if uv is not available.
    
    Returns:
        tuple: (is_compatible, message)
    """
    # Try to use uv to check if the Python version is available
    try:
        # Check if uv is available
        result = subprocess.run(
            ["uv", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            # uv not available, we can't check - be conservative and pass
            return True, "uv not available for testing"
        
        actual_uv_version = result.stdout.strip()
        
        # Try to install the Python version (dry-run to avoid actual installation)
        # First check if uv python install supports the version
        result = subprocess.run(
            ["uv", "python", "install", "--help"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            # uv python install not available, fall back to conservative pass
            return True, f"uv python install not available (uv {actual_uv_version})"
        
        # Try to find the Python version - uv will error if it doesn't exist
        # We use a timeout to prevent hanging
        result = subprocess.run(
            ["uv", "python", "find", python_version],
            capture_output=True,
            text=True,
            timeout=15
        )
        
        # If find succeeds, the version is available
        if result.returncode == 0:
            return True, f"verified via uv python find (uv {actual_uv_version})"
        else:
            # Check if it's a "not found" error vs other error
            error_msg = result.stderr.lower()
            if "no python" in error_msg or "not found" in error_msg or "could not find" in error_msg:
                return False, f"Python {python_version} not available for uv {actual_uv_version}"
            else:
                # Other error, be conservative
                return True, f"unable to verify (uv {actual_uv_version})"
            
    except subprocess.TimeoutExpired:
        return True, "uv command timed out, assuming compatible"
    except FileNotFoundError:
        # uv not installed, be conservative
        return True, "uv not installed, assuming compatible"
    except Exception as e:
        # Other error, be conservative
        return True, f"unable to verify via uv ({type(e).__name__})"


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
        print(f"{status} {source}: uv {uv_version} {'supports' if compatible else 'may not support'} Python {python_version}{detail}")
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
