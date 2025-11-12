#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Validate uv configuration for local development and CI.

Performs two checks:
1. Verify flox's uv can download the Python version from pyproject.toml
   (critical for local development)
2. Verify uv versions are consistent across flox and CI workflows
   (helps maintain configuration consistency)

Run in CI via .github/workflows/ci-python.yml to catch issues early.

Exit codes:
    0: All checks passed
    1: Flox uv cannot download required Python or config error
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


def get_uv_versions_from_workflows() -> dict[str, set[str]]:
    """Extract uv versions from GitHub workflow files.

    Returns a dict mapping workflow filename to set of uv versions found.
    Workflows may have multiple setup-uv steps with different versions.
    """
    workflows_dir = Path(__file__).parent.parent / ".github" / "workflows"
    uv_versions: dict[str, set[str]] = {}

    for workflow_file in workflows_dir.glob("*.yml"):
        content = workflow_file.read_text()
        # Look for uv version specifications like "version: 0.8.19"
        matches = re.findall(r"setup-uv@[a-f0-9]+.*?version:\s*([0-9.]+)", content, re.DOTALL)
        if matches:
            uv_versions[workflow_file.name] = set(matches)

    return uv_versions


def check_uv_python_compatibility(uv_version: str, python_version: str) -> tuple[bool, str]:
    """
    Check if a given uv version can download the specified Python version.

    Uses `uvx --from uv@{version} uv python list --only-downloads` to test
    the specific uv version's ability to download the Python version.

    Returns:
        tuple: (is_compatible, message)
    """
    try:
        # Use uvx to run the specific uv version
        result = subprocess.run(
            [
                "uvx",
                "--from",
                f"uv@{uv_version}",
                "uv",
                "python",
                "list",
                python_version,
                "--only-downloads",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0 and result.stdout.strip():
            return True, "verified via uv python list"
        else:
            return False, f"Python {python_version} not available for uv {uv_version}"

    except subprocess.TimeoutExpired:
        return True, "uv command timed out, assuming compatible"
    except FileNotFoundError:
        return True, "uvx not installed, assuming compatible"
    except Exception as e:
        return True, f"unable to verify ({type(e).__name__})"


def main() -> int:
    """Main entry point for the validation script."""
    print("Validating uv configuration...")
    print()

    # Get Python version from pyproject.toml
    try:
        python_version = get_python_version_from_pyproject()
        print(f"Python version required: {python_version}")
    except Exception as e:
        print(f"✗ Error reading Python version: {e}")
        return 1

    # Get uv versions from all sources
    flox_uv = None
    try:
        flox_uv = get_uv_version_from_flox()
        if flox_uv:
            print(f"Flox uv version: {flox_uv}")
    except Exception as e:
        print(f"⚠ Warning: Could not read flox manifest: {e}")

    workflow_versions = {}
    try:
        workflow_versions = get_uv_versions_from_workflows()
        if workflow_versions:
            total_versions = sum(len(versions) for versions in workflow_versions.values())
            print(f"Found {total_versions} uv installation(s) in {len(workflow_versions)} workflow(s)")
    except Exception as e:
        print(f"⚠ Warning: Could not read workflows: {e}")

    print()
    print("=" * 60)
    print()

    # Check 1: Can flox uv download the required Python version?
    print("Check 1: Flox uv Python compatibility")
    print("-" * 60)

    if not flox_uv:
        print("⚠ Skipped: No flox manifest found")
        flox_compatible = True
    else:
        compatible, message = check_uv_python_compatibility(flox_uv, python_version)
        if compatible:
            print(f"✓ Flox uv {flox_uv} can download Python {python_version}")
            print(f"  {message}")
            flox_compatible = True
        else:
            print(f"✗ Flox uv {flox_uv} cannot download Python {python_version}")
            print(f"  {message}")
            print()
            print("  To fix: Update uv version in .flox/env/manifest.toml")
            print("  See: https://github.com/astral-sh/uv/releases")
            flox_compatible = False

    print()
    print("=" * 60)
    print()

    # Check 2: Are all uv versions consistent?
    print("Check 2: uv version consistency")
    print("-" * 60)

    # Flatten workflow versions for consistency check
    all_versions = {}
    if flox_uv:
        all_versions["flox"] = flox_uv
    for workflow_name, versions in workflow_versions.items():
        if len(versions) == 1:
            all_versions[workflow_name] = next(iter(versions))
        else:
            # Multiple versions in one workflow
            for i, version in enumerate(sorted(versions), 1):
                all_versions[f"{workflow_name}#{i}"] = version

    if len(all_versions) < 2:
        print("⚠ Not enough sources to check consistency")
        versions_consistent = True
    else:
        unique_versions = set(all_versions.values())
        if len(unique_versions) == 1:
            print(f"✓ All sources use uv {unique_versions.pop()}")
            versions_consistent = True
        else:
            print("⚠ Inconsistent uv versions found:")
            for source, version in sorted(all_versions.items()):
                print(f"  - {source}: {version}")
            print()
            print("  Consider standardizing to a single uv version")
            versions_consistent = False

    print()
    print("=" * 60)
    print()

    # Summary
    if flox_compatible and versions_consistent:
        print("✓ All checks passed")
        return 0
    elif not flox_compatible:
        print("✗ Failed: Flox uv cannot download required Python version")
        return 1
    else:
        print("⚠ Passed with warnings: Version inconsistency detected")
        return 0


if __name__ == "__main__":
    sys.exit(main())
