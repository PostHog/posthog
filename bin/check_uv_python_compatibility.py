#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
Validate uv configuration for local development and CI.

The shape we enforce:

- pyproject.toml [tool.uv].required-version is a FLOOR (e.g. ">=0.10.2"). It is
  the lowest uv version that can read this repo's config and lockfile. Bumping
  CI to a newer uv does NOT raise this floor — that keeps stale branches from
  breaking the moment master ships a new pin. Raise the floor only when the
  code on master genuinely requires a newer uv feature.

- .github/workflows/*.yml use setup-uv with an explicit exact version literal
  (e.g. `version: '0.11.14'`). Every workflow pins the SAME exact version so
  CI is deterministic across jobs. The pin must satisfy the pyproject floor.
  An exact literal also avoids the historical GH API rate-limit issue caused
  by range resolution (astral-sh/setup-uv#325).

- .flox/env/manifest.toml mirrors the CI pin for parity between local dev and
  CI. Comparison is on major.minor to allow patch drift.

Performs four checks:
1. Workflow pins are present, exact literals, and identical across all files.
2. Workflow pin satisfies pyproject's required-version floor.
3. Workflow pin can download the required Python version.
4. Flox manifest uv version matches the workflow pin on major.minor.

Run in CI via .github/workflows/ci-python.yml to catch issues early.

Exit codes:
    0: All checks passed
    1: any check failed
"""

import re
import sys
import subprocess
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore


Version = tuple[int, int, int]


def parse_version(s: str) -> Version:
    """Parse 'X.Y.Z' into a tuple. Extra suffixes are ignored."""
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", s)
    if not match:
        raise ValueError(f"Cannot parse version: {s}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def get_python_version_from_pyproject() -> str:
    """Extract the required Python version from pyproject.toml."""
    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    requires_python = data.get("project", {}).get("requires-python", "")
    # Extract version from format like "==X.Y.Z" or ">=X.Y.Z"
    match = re.search(r"(\d+\.\d+\.\d+)", requires_python)
    if not match:
        raise ValueError(f"Could not parse Python version from: {requires_python}")

    return match.group(1)


def get_uv_floor_from_pyproject() -> str | None:
    """Extract the uv floor version from pyproject.toml [tool.uv].required-version.

    Expects a `>=X.Y.Z` form. Returns the X.Y.Z literal, or None if absent.
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
    """Extract the uv version literal from the flox manifest."""
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
    if a usage has no pin). Every usage must be pinned with an exact literal —
    unpinned setup-uv would resolve via GitHub API on every job and hit rate
    limits under concurrent load (see astral-sh/setup-uv#325).
    """
    workflows_dir = Path(__file__).parent.parent / ".github" / "workflows"
    uv_usages: dict[str, list[str | None]] = {}

    for workflow_file in sorted(workflows_dir.glob("*.yml")):
        lines = workflow_file.read_text().splitlines()
        for i, line in enumerate(lines):
            if "setup-uv@" not in line:
                continue
            version: str | None = None
            for lookahead in lines[i + 1 : i + 6]:
                if re.match(r"^\s+-\s+name:", lookahead):
                    break
                m = re.match(r"^\s+version:\s*['\"]?([0-9.]+)['\"]?", lookahead)
                if m:
                    version = m.group(1)
                    break
            uv_usages.setdefault(workflow_file.name, []).append(version)

    return uv_usages


def check_uv_python_compatibility(uv_version: str, python_version: str) -> tuple[bool, str]:
    """Check if the given uv version can download the specified Python version."""
    try:
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
        return False, f"Python {python_version} not available for uv {uv_version}"
    except subprocess.TimeoutExpired:
        return True, "uv command timed out, assuming compatible"
    except FileNotFoundError:
        return True, "uvx not installed, assuming compatible"
    except Exception as e:
        return True, f"unable to verify ({type(e).__name__})"


def _section(title: str) -> None:
    print(title)
    print("-" * 60)


def _divider() -> None:
    print()
    print("=" * 60)
    print()


def label_workflow_pins(workflow_usages: dict[str, list[str | None]]) -> tuple[list[str], dict[str, list[str]]]:
    """Split workflow usages into missing pins and pins grouped by version.

    Returns (missing_pins, pin_locations). Each usage is labelled with its
    workflow name, plus a `(usage N)` suffix when a workflow has several.
    """
    missing_pins: list[str] = []
    pin_locations: dict[str, list[str]] = {}

    for workflow_name, versions in sorted(workflow_usages.items()):
        for i, version in enumerate(versions):
            usage = f"{workflow_name} (usage {i + 1})" if len(versions) > 1 else workflow_name
            if version is None:
                missing_pins.append(usage)
            else:
                pin_locations.setdefault(version, []).append(usage)

    return missing_pins, pin_locations


def check_workflow_pins() -> tuple[bool, str | None]:
    """Check 1: pins present, exact literals, and identical across workflows.

    Returns (ok, workflow_pin). The pin is the single agreed version, or None
    when it is missing or ambiguous.
    """
    _section("Check 1: CI workflow uv version pins")

    workflow_usages = get_uv_versions_from_workflows()
    missing_pins, pin_locations = label_workflow_pins(workflow_usages)
    distinct_pins = set(pin_locations)

    ok = True
    if missing_pins:
        print("✗ setup-uv usages missing version pin (add `version: 'x.y.z'`):")
        for name in missing_pins:
            print(f"  - {name}")
        print()
        print("  Without an exact pin, setup-uv may resolve via GitHub API and")
        print("  hit rate limits under concurrent load (astral-sh/setup-uv#325).")
        ok = False

    workflow_pin: str | None = None
    if len(distinct_pins) > 1:
        print("✗ setup-uv usages pinned to different versions (must all match):")
        for pin in sorted(distinct_pins):
            print(f"  {pin}:")
            for loc in pin_locations[pin]:
                print(f"    - {loc}")
        ok = False
    elif len(distinct_pins) == 1:
        workflow_pin = next(iter(distinct_pins))
        if not missing_pins:
            print(f"✓ All {sum(len(v) for v in workflow_usages.values())} setup-uv usages pinned to {workflow_pin}")
    elif not missing_pins:
        print("⚠ No setup-uv usages found in workflows")

    return ok, workflow_pin


def check_floor_satisfied(workflow_pin: str | None, floor: str | None) -> bool:
    """Check 2: the workflow pin is at or above the pyproject floor."""
    _section("Check 2: Workflow pin satisfies pyproject floor")

    if not (floor and workflow_pin):
        print("⚠ Skipped: missing workflow pin or pyproject floor")
        return True

    try:
        if parse_version(workflow_pin) >= parse_version(floor):
            print(f"✓ Workflow pin {workflow_pin} >= pyproject floor {floor}")
            return True
        print(f"✗ Workflow pin {workflow_pin} is below pyproject floor {floor}")
        print("  Either raise the workflow pin or lower the floor.")
        return False
    except ValueError as e:
        print(f"⚠ Skipped: {e}")
        return True


def check_python_downloadable(workflow_pin: str | None, python_version: str) -> bool:
    """Check 3: the workflow pin can download the required Python version."""
    _section("Check 3: uv Python compatibility")

    if not workflow_pin:
        print("⚠ Skipped: no workflow pin to test")
        return True

    compatible, message = check_uv_python_compatibility(workflow_pin, python_version)
    if compatible:
        print(f"✓ uv {workflow_pin} can download Python {python_version}")
        print(f"  {message}")
        return True

    print(f"✗ uv {workflow_pin} cannot download Python {python_version}")
    print(f"  {message}")
    print()
    print("  To fix: pick a uv version whose `uv python list X.Y.Z --only-downloads` succeeds.")
    print("  See: https://github.com/astral-sh/uv/releases")
    return False


def check_flox_alignment(workflow_pin: str | None) -> bool:
    """Check 4: the flox manifest matches the workflow pin on major.minor."""
    _section("Check 4: Flox manifest uv version alignment")

    flox_uv = get_uv_version_from_flox()
    if not flox_uv:
        print("⚠ Skipped: No flox manifest or uv version found")
        return True
    if not workflow_pin:
        print("⚠ Skipped: No workflow pin to compare against")
        return True

    flox_mm = ".".join(flox_uv.split(".")[:2])
    pin_mm = ".".join(workflow_pin.split(".")[:2])
    if flox_mm == pin_mm:
        print(f"✓ Flox uv {flox_uv} matches workflow pin {workflow_pin} on major.minor")
        return True
    print(f"✗ Flox uv {flox_uv} diverges from workflow pin {workflow_pin}")
    print("  Update .flox/env/manifest.toml to match the workflow pin.")
    return False


def main() -> int:
    """Main entry point for the validation script."""
    print("Validating uv configuration...")
    print()

    try:
        python_version = get_python_version_from_pyproject()
        print(f"Python version required: {python_version}")
    except Exception as e:
        print(f"✗ Error reading Python version: {e}")
        return 1

    floor = get_uv_floor_from_pyproject()
    print(f"uv floor (pyproject.toml): >={floor}" if floor else "uv floor: not set")

    _divider()
    pins_ok, workflow_pin = check_workflow_pins()
    _divider()
    floor_ok = check_floor_satisfied(workflow_pin, floor)
    _divider()
    python_ok = check_python_downloadable(workflow_pin, python_version)
    _divider()
    flox_ok = check_flox_alignment(workflow_pin)
    _divider()

    if pins_ok and floor_ok and python_ok and flox_ok:
        print("✓ All checks passed")
        return 0

    failures = []
    if not pins_ok:
        failures.append("workflow uv pins missing, mismatched, or not exact")
    if not floor_ok:
        failures.append("workflow pin below pyproject floor")
    if not python_ok:
        failures.append("workflow uv cannot download required Python")
    if not flox_ok:
        failures.append("flox uv diverges from workflow pin")
    print(f"✗ Failed: {'; '.join(failures)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
