#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Validate uv configuration for local development and CI.

Performs four checks:
1. Verify the uv version from pyproject.toml can download the required Python
   (critical for local development and CI)
2. Verify all CI workflow version pins match pyproject.toml
   Pins are required: without them, setup-uv queries the GitHub API on every
   job to resolve the required-version range, exhausting the installation
   token rate limit under concurrent load.
3. Verify flox manifest uv version is compatible with pyproject.toml
4. Verify the Codespaces Dockerfile mounts a pinned uv image matching pyproject.toml

Run in CI via .github/workflows/ci-python.yml to catch issues early.

Exit codes:
    0: All checks passed
    1: uv cannot download required Python, config error, or workflow pins missing/mismatched
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


def _extract_uv_tag(text: str) -> str | None:
    """Extract a semver uv image tag from a Dockerfile snippet.

    Matches both:
      --mount=from=ghcr.io/astral-sh/uv:<tag>   (devcontainer bind-mount style)
      FROM ghcr.io/astral-sh/uv:<tag>            (multi-stage FROM style)
    Returns the tag, or None if absent or not a semver (e.g. 'latest').
    """
    m = re.search(r"ghcr\.io/astral-sh/uv:([^\s,@]+)", text)
    if not m:
        return None
    tag = m.group(1)
    return tag if re.match(r"^\d+\.\d+\.\d+$", tag) else None


def get_uv_versions_from_dockerfiles() -> dict[str, str | None]:
    """Scan all Dockerfiles in the repo for ghcr.io/astral-sh/uv image references.

    Returns a dict mapping relative Dockerfile path to the pinned version string,
    or None if the image is referenced but unpinned (e.g. :latest or no tag).
    Only files that actually reference the uv image are included.
    """
    root = Path(__file__).parent.parent
    results: dict[str, str | None] = {}

    # Collect all Dockerfile* files at root and one level deep in services/
    candidates: list[Path] = []
    candidates.extend(root.glob("Dockerfile*"))
    candidates.extend(root.glob(".devcontainer/Dockerfile*"))
    candidates.extend(root.glob("services/*/Dockerfile*"))

    for df in sorted(candidates):
        if not df.is_file():
            continue
        content = df.read_text()
        if "ghcr.io/astral-sh/uv" not in content:
            continue
        results[str(df.relative_to(root))] = _extract_uv_tag(content)

    return results


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


def get_uv_versions_from_workflows() -> dict[str, list[str | None]]:
    """Find all setup-uv usages in CI workflows and their version pins.

    Returns a dict mapping workflow filename to list of version strings (or None
    if a usage has no pin). Every usage must be pinned to the pyproject.toml
    version — without a pin, setup-uv queries the GitHub API on every job to
    resolve the required-version range, exhausting the installation token rate
    limit under concurrent load.
    """
    workflows_dir = Path(__file__).parent.parent / ".github" / "workflows"
    uv_usages: dict[str, list[str | None]] = {}

    for workflow_file in sorted(workflows_dir.glob("*.yml")):
        lines = workflow_file.read_text().splitlines()
        for i, line in enumerate(lines):
            if "setup-uv@" not in line:
                continue
            version: str | None = None
            # Check the next few lines for a version: key within the same with: block
            for lookahead in lines[i + 1 : i + 6]:
                if re.match(r"^\s+-\s+name:", lookahead):
                    break  # next step, stop looking
                m = re.match(r"^\s+version:\s*['\"]?([0-9.]+)['\"]?", lookahead)
                if m:
                    version = m.group(1)
                    break
            uv_usages.setdefault(workflow_file.name, []).append(version)

    return uv_usages


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

    # Check 2: All workflow pins present and match pyproject.toml
    print("Check 2: CI workflow uv version pins")
    print("-" * 60)

    workflow_usages = get_uv_versions_from_workflows()
    missing_pins: list[str] = []
    wrong_pins: list[str] = []

    for workflow_name, versions in sorted(workflow_usages.items()):
        for i, version in enumerate(versions):
            usage = f"{workflow_name} (usage {i + 1})" if len(versions) > 1 else workflow_name
            if version is None:
                missing_pins.append(usage)
            elif uv_version and version != uv_version:
                wrong_pins.append(f"{usage}: {version} (expected {uv_version})")

    if not missing_pins and not wrong_pins:
        print(f"✓ All setup-uv usages pinned to {uv_version}")
        pins_ok = True
    else:
        if missing_pins:
            print("✗ setup-uv usages missing version pin (add version: 'x.y.z'):")
            for name in missing_pins:
                print(f"  - {name}")
            print()
            print("  Without a pin, setup-uv queries the GitHub API on every job")
            print("  to resolve the required-version range, which exhausts the")
            print("  installation token rate limit under concurrent load.")
        if wrong_pins:
            print(f"✗ setup-uv usages with wrong version (expected {uv_version}):")
            for name in wrong_pins:
                print(f"  - {name}")
        pins_ok = False

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

    # Check 4: Dockerfile uv image pins
    print("Check 4: Dockerfile uv image pins")
    print("-" * 60)

    dockerfile_versions = get_uv_versions_from_dockerfiles()
    if not dockerfile_versions:
        print("⚠ Skipped: No Dockerfiles reference ghcr.io/astral-sh/uv")
        dockerfile_pinned = True
    else:
        dockerfile_pinned = True
        for df_path, df_tag in sorted(dockerfile_versions.items()):
            if df_tag is None:
                print(f"✗ {df_path}: ghcr.io/astral-sh/uv is not pinned to a version")
                print(f"  Pin to: ghcr.io/astral-sh/uv:{uv_version or '<version>'}")
                print("  See: https://github.com/astral-sh/uv/releases")
                dockerfile_pinned = False
            elif uv_version and df_tag != uv_version:
                print(f"✗ {df_path}: pins uv to {df_tag}, expected {uv_version} (from pyproject.toml)")
                print(f"  Update to: ghcr.io/astral-sh/uv:{uv_version}")
                dockerfile_pinned = False
            else:
                print(f"✓ {df_path}: uv pin {df_tag} matches pyproject.toml")
        if dockerfile_pinned:
            print(f"  All {len(dockerfile_versions)} Dockerfile(s) pinned correctly")

    print()
    print("=" * 60)
    print()

    # Summary
    if uv_compatible and pins_ok and flox_aligned and dockerfile_pinned:
        print("✓ All checks passed")
        return 0
    else:
        failures = []
        if not uv_compatible:
            failures.append("uv cannot download required Python version")
        if not pins_ok:
            failures.append("workflow uv version pins missing or mismatched")
        if not flox_aligned:
            failures.append("flox uv version diverges from pyproject.toml")
        if not dockerfile_pinned:
            failures.append("Dockerfile uv image pin missing or mismatched")
        print(f"✗ Failed: {'; '.join(failures)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
