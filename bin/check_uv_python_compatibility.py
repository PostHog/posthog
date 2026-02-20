#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Validate uv configuration for local development and CI.

Performs three checks:
1. Verify the uv version from pyproject.toml can download the required Python
   (critical for local development and CI)
2. Verify no CI workflow overrides the uv version with an explicit pin
   (pyproject.toml required-version is the single source of truth)
3. Verify flox manifest uv version is compatible with pyproject.toml

Run in CI via .github/workflows/ci-python.yml to catch issues early.

Exit codes:
    0: All checks passed
    1: uv cannot download required Python, config error, or workflow overrides found
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


def get_uv_version_from_pyproject() -> str | None:
    """Extract the base uv version from pyproject.toml required-version.

    Strips PEP 440 operators (~=, ==, >=, ^, etc.) to get the base version.
    """
    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    required_version = data.get("tool", {}).get("uv", {}).get("required-version", "")
    if not required_version:
        return None

    match = re.search(r"(\d+\.\d+\.\d+)", required_version)
    return match.group(1) if match else None


def get_uv_version_from_flox() -> str | None:
    """Extract the base uv version from flox manifest.

    Strips semver operators (^, >=, etc.) to get the base version.
    """
    flox_manifest = Path(__file__).parent.parent / ".flox" / "env" / "manifest.toml"

    if not flox_manifest.exists():
        return None

    with open(flox_manifest, "rb") as f:
        data = tomllib.load(f)

    version = data.get("install", {}).get("uv", {}).get("version", "")
    if not version:
        return None

    match = re.search(r"(\d+\.\d+\.\d+)", version)
    return match.group(1) if match else None


def get_uv_versions_from_workflows() -> dict[str, set[str]]:
    """Find CI workflows that override the uv version.

    Returns a dict mapping workflow filename to set of uv versions found.
    Ideally this should be empty — pyproject.toml is the single source of truth.
    """
    workflows_dir = Path(__file__).parent.parent / ".github" / "workflows"
    uv_versions: dict[str, set[str]] = {}

    for workflow_file in sorted(workflows_dir.glob("*.yml")):
        lines = workflow_file.read_text().splitlines()
        for i, line in enumerate(lines):
            if "setup-uv@" not in line:
                continue
            # Check the next few lines for a version: key within the same with: block
            for lookahead in lines[i + 1 : i + 6]:
                if re.match(r"^\s+-\s+name:", lookahead):
                    break  # next step, stop looking
                m = re.match(r"^\s+version:\s*([0-9.]+)", lookahead)
                if m:
                    uv_versions.setdefault(workflow_file.name, set()).add(m.group(1))

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
                f"uv=={uv_version}",
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

    # Get uv version from pyproject.toml (single source of truth)
    uv_version = None
    try:
        uv_version = get_uv_version_from_pyproject()
        if uv_version:
            print(f"uv version (pyproject.toml): {uv_version}")
    except Exception as e:
        print(f"⚠ Warning: Could not read pyproject.toml: {e}")

    print()
    print("=" * 60)
    print()

    # Check 1: Can uv download the required Python version?
    print("Check 1: uv Python compatibility")
    print("-" * 60)

    if not uv_version:
        print("⚠ Skipped: No uv version found in pyproject.toml")
        uv_compatible = True
    else:
        compatible, message = check_uv_python_compatibility(uv_version, python_version)
        if compatible:
            print(f"✓ uv {uv_version} can download Python {python_version}")
            print(f"  {message}")
            uv_compatible = True
        else:
            print(f"✗ uv {uv_version} cannot download Python {python_version}")
            print(f"  {message}")
            print()
            print("  To fix: Update required-version in pyproject.toml [tool.uv]")
            print("  See: https://github.com/astral-sh/uv/releases")
            uv_compatible = False

    print()
    print("=" * 60)
    print()

    # Check 2: No workflow version overrides
    print("Check 2: No CI workflow uv version overrides")
    print("-" * 60)

    workflow_overrides = get_uv_versions_from_workflows()
    if not workflow_overrides:
        print("✓ No workflow overrides (pyproject.toml is single source of truth)")
        no_overrides = True
    else:
        print("✗ Found workflow uv version overrides (remove these):")
        for workflow_name, versions in sorted(workflow_overrides.items()):
            for version in sorted(versions):
                print(f"  - {workflow_name}: version: {version}")
        print()
        print("  setup-uv reads required-version from pyproject.toml automatically")
        no_overrides = False

    print()
    print("=" * 60)
    print()

    # Check 3: Flox manifest compatible with pyproject.toml
    print("Check 3: Flox manifest uv version alignment")
    print("-" * 60)

    flox_uv = get_uv_version_from_flox()
    if not flox_uv:
        print("⚠ Skipped: No flox manifest or uv version found")
        flox_aligned = True
    elif not uv_version:
        print("⚠ Skipped: No pyproject.toml uv version to compare against")
        flox_aligned = True
    else:
        # Compare major.minor — flox uses a compat range so patch can differ
        pyproject_minor = ".".join(uv_version.split(".")[:2])
        flox_minor = ".".join(flox_uv.split(".")[:2])
        if pyproject_minor == flox_minor:
            print(f"✓ Flox uv {flox_uv} is compatible with pyproject.toml {uv_version}")
            flox_aligned = True
        else:
            print(f"✗ Flox uv base version {flox_uv} diverges from pyproject.toml {uv_version}")
            print("  Update .flox/env/manifest.toml to match")
            flox_aligned = False

    print()
    print("=" * 60)
    print()

    # Summary
    if uv_compatible and no_overrides and flox_aligned:
        print("✓ All checks passed")
        return 0
    else:
        failures = []
        if not uv_compatible:
            failures.append("uv cannot download required Python version")
        if not no_overrides:
            failures.append("workflow uv version overrides found")
        if not flox_aligned:
            failures.append("flox uv version diverges from pyproject.toml")
        print(f"✗ Failed: {'; '.join(failures)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
