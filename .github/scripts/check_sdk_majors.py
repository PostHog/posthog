#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""
CI check: every PostHog SDK this repo installs stays on the major it was migrated to.

A new SDK major removes legacy capture and changes the capture API, so taking one is a
reviewed migration, never a routine bump. The SDK release bots rewrite these manifests
on every release, so the declared spec alone cannot hold the line: this checks every
manifest that names an SDK, the resolved lockfile versions, and the SDK range each
wrapper package accepts.

To take a major on purpose, raise its entry in EXPECTED_MAJORS in the PR that moves the
call sites.

Usage:
    python3 .github/scripts/check_sdk_majors.py

Exit codes:
    0 - every SDK is on its expected major
    1 - a manifest, lockfile or wrapper peer range reaches another major
"""

from __future__ import annotations

import re
import sys
import json
import tomllib
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKIPPED_DIRS = {"node_modules", ".git", "dist", ".venv", "target", ".flox", "build"}

# posthog-python is published under two names: `posthoganalytics` for this repo (its
# Django package is also called posthog) and `posthog` everywhere else.
EXPECTED_MAJORS = {
    "posthoganalytics": 7,
    "posthog": 7,
    "posthog-node": 5,
    "posthog-js": 1,
    "@posthog/react": 1,
    "posthog-js-lite": 4,
    "posthog-react-native": 4,
    "posthog-rs": 0,
    "posthog-go": 1,
}
NPM_SDKS = ("posthog-node", "posthog-js", "@posthog/react", "posthog-js-lite", "posthog-react-native")
NPM_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")

# pnpm workspaces: (manifest path prefix, workspace file, lockfile). The first match wins.
NPM_WORKSPACES = (
    ("products/desktop/", "products/desktop/pnpm-workspace.yaml", "products/desktop/pnpm-lock.yaml"),
    ("", "pnpm-workspace.yaml", "pnpm-lock.yaml"),
)

# Wrapper packages that depend on an SDK. A routine wrapper release can raise its peer
# range to the next SDK major, which is the same breaking change through a side door.
NODE_WRAPPER_PEERS = (
    ("pnpm-lock.yaml", "@posthog/react", "posthog-js"),
    ("pnpm-lock.yaml", "@posthog/mcp", "posthog-node"),
)

# (manifest, package, lockfile or None)
PYTHON_PINS = (
    ("pyproject.toml", "posthoganalytics", "uv.lock"),
    ("services/llm-gateway/pyproject.toml", "posthoganalytics", "services/llm-gateway/uv.lock"),
    ("common/ingestion/acceptance_tests/requirements.txt", "posthoganalytics", None),
    ("tools/infra-scripts/clitools/requirements.txt", "posthog", None),
)

# (manifest, TOML path to the dependency table, lockfile). posthog-rs is 0.x, so Cargo
# already treats every minor as breaking and the bot bumps those routinely; the guard
# holds only the major, which keeps 1.0 out until its migration.
RUST_PINS = (
    ("rust/Cargo.toml", ("workspace", "dependencies"), "rust/Cargo.lock"),
    ("cli/Cargo.toml", ("dependencies",), "cli/Cargo.lock"),
)

GO_MODULE = "github.com/posthog/posthog-go"
GO_MANIFEST = "bin/hobby-installer/go.mod"
GO_SUM = "bin/hobby-installer/go.sum"

MIGRATION_HINT = "A new SDK major needs a migration PR; raise EXPECTED_MAJORS there."


class MajorRange(NamedTuple):
    low: int
    high: int | None  # inclusive; None means no upper bound


def _major(version: str) -> int:
    match = re.match(r"v?(\d+)", version)
    if not match:
        raise ValueError(f"cannot read a major from {version!r}")
    return int(match.group(1))


def _is_next_major_boundary(version: str, major: int) -> bool:
    """True for a version that is exactly the first release of major + 1, such as 8, 8.0 or 8.0.0."""
    return re.fullmatch(rf"v?{major + 1}(\.0)*(-0)?", version) is not None


def _named(package: str) -> re.Pattern[str]:
    """Match `package` followed by an operator, an extra, or the end, never a longer name."""
    return re.compile(rf"^{re.escape(package)}(\[|[^A-Za-z0-9_.-]|$)")


def npm_ranges(spec: str) -> list[MajorRange]:
    """The majors an npm range admits, one MajorRange per `||` alternative."""
    ranges = []
    for alternative in spec.split("||"):
        alternative = alternative.strip()
        if alternative in ("", "*", "latest", "x") or alternative.startswith(("workspace:", "catalog:", "npm:")):
            ranges.append(MajorRange(0, None))
            continue
        low, high = 0, None
        for token in alternative.split():
            if token.startswith(("^", "~", "=")):
                major = _major(token.lstrip("^~="))
                low, high = max(low, major), major if high is None else min(high, major)
            elif token.startswith(">="):
                low = max(low, _major(token[2:]))
            elif token.startswith(">"):
                # A bare `>5` excludes every 5.x; `>5.1` means `>=5.2.0` and still admits major 5.
                bound = token[1:]
                low = max(low, _major(bound) + 1 if re.fullmatch(r"v?\d+", bound) else _major(bound))
            elif token.startswith("<="):
                high = _major(token[2:]) if high is None else min(high, _major(token[2:]))
            elif token.startswith("<"):
                bound = token[1:]
                cap = _major(bound) - 1 if _is_next_major_boundary(bound, _major(bound) - 1) else _major(bound)
                high = cap if high is None else min(high, cap)
            else:
                major = _major(token.replace("x", "0"))
                low, high = max(low, major), major if high is None else min(high, major)
        ranges.append(MajorRange(low, high))
    return ranges


def npm_pinned_to(spec: str, expected: int) -> bool:
    return all(r.low == expected and r.high == expected for r in npm_ranges(spec))


def npm_admits(spec: str, expected: int) -> bool:
    return any(r.low <= expected and (r.high is None or expected <= r.high) for r in npm_ranges(spec))


def pnpm_catalog(workspace_file: Path) -> dict[str, str]:
    catalog: dict[str, str] = {}
    in_catalog = False
    for line in workspace_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("catalog:"):
            in_catalog = True
            continue
        if in_catalog and line and not line.startswith(" "):
            break
        match = re.match(r"^\s+'?([^':\s]+)'?:\s*'?([^'#]+?)'?\s*(#.*)?$", line) if in_catalog else None
        if match:
            catalog[match.group(1)] = match.group(2)
    return catalog


def pnpm_lock_majors(lock_text: str, package: str) -> set[int]:
    pattern = re.compile(rf"^  '?{re.escape(package)}@(\d+)\.", re.MULTILINE)
    return {int(m.group(1)) for m in pattern.finditer(lock_text)}


def pnpm_lock_peer_ranges(lock_text: str, package: str, peer: str) -> dict[str, str]:
    """Every version of `package` in the lock's packages section, with the range it declares on `peer`."""
    ranges = {}
    for entry in re.finditer(rf"^  '{re.escape(package)}@([^(']+)':\n((?:    .*\n)+)", lock_text, re.MULTILINE):
        peer_line = re.search(rf"^      '?{re.escape(peer)}'?:\s*'?([^'\n]+?)'?$", entry.group(2), re.MULTILINE)
        ranges[entry.group(1)] = peer_line.group(1) if peer_line else ""
    return ranges


def npm_workspace_for(manifest: str) -> tuple[str, str]:
    for prefix, workspace_file, lock in NPM_WORKSPACES:
        if manifest.startswith(prefix):
            return workspace_file, lock
    raise AssertionError("unreachable: the root workspace matches every path")


def npm_manifests(root: Path) -> list[tuple[str, str, str, str]]:
    """Every (manifest, section, package, spec) under root that names an npm SDK."""
    found = []
    for path in sorted(root.rglob("package.json")):
        if SKIPPED_DIRS.intersection(path.parts):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        manifest = path.relative_to(root).as_posix()
        for section in NPM_SECTIONS:
            deps = data.get(section)
            if not isinstance(deps, dict):
                continue
            for package in NPM_SDKS:
                if package in deps:
                    found.append((manifest, section, package, deps[package]))
    return found


def pep440_clauses(spec: str) -> list[tuple[str, str]]:
    body = re.sub(r"^[A-Za-z0-9_.-]+(\[[^\]]*\])?", "", spec.strip())
    return [(m.group(1), m.group(2)) for m in re.finditer(r"(===|==|~=|!=|<=|>=|<|>)\s*([0-9][0-9A-Za-z.*+!-]*)", body)]


def python_floor_major(spec: str) -> int:
    floors = [_major(v) for op, v in pep440_clauses(spec) if op in ("==", "===", "~=", ">=", ">")]
    if not floors:
        raise ValueError(f"{spec!r} has no lower bound")
    return max(floors)


def python_capped_at(major: int, *specs: str) -> bool:
    """True when the specs together exclude every version of major + 1."""
    for spec in specs:
        for op, version in pep440_clauses(spec):
            if op in ("==", "===", "~="):
                return True
            if op == "<" and (_major(version) <= major or _is_next_major_boundary(version, major)):
                return True
            if op == "<=" and _major(version) <= major:
                return True
    return False


def requirements_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]


def cargo_requirement_major(requirement: str) -> int:
    """Cargo treats a bare version as a caret, so `0.27.0` admits only 0.27.x."""
    if re.search(r"[*<>,]", requirement) or not requirement.strip():
        raise ValueError(f"{requirement!r} is not a caret, tilde or exact requirement, so it can float across majors")
    return _major(requirement.lstrip("^~="))


def _lock_package_major(lock_path: Path, package: str) -> int:
    packages = tomllib.loads(lock_path.read_text(encoding="utf-8"))["package"]
    return _major(next(p["version"] for p in packages if p["name"] == package))


def check_node(root: Path) -> list[str]:
    problems = []
    for manifest, section, package, spec in npm_manifests(root):
        workspace_file, _lock = npm_workspace_for(manifest)
        expected = EXPECTED_MAJORS[package]
        if spec == "catalog:":
            spec = pnpm_catalog(root / workspace_file).get(package, "")
        if not npm_pinned_to(spec, expected):
            problems.append(
                f"{manifest} [{section}]: {package} declares {spec!r}, which is not pinned to major {expected}. {MIGRATION_HINT}"
            )
    for _prefix, workspace_file, lock in NPM_WORKSPACES:
        catalog = pnpm_catalog(root / workspace_file)
        for package in NPM_SDKS:
            if package in catalog and not npm_pinned_to(catalog[package], EXPECTED_MAJORS[package]):
                problems.append(
                    f"{workspace_file} catalog: {package} is {catalog[package]!r}, expected major {EXPECTED_MAJORS[package]}"
                )
        lock_text = (root / lock).read_text(encoding="utf-8")
        for package in NPM_SDKS:
            resolved = pnpm_lock_majors(lock_text, package)
            if resolved and resolved != {EXPECTED_MAJORS[package]}:
                problems.append(
                    f"{lock} resolves {package} to majors {sorted(resolved)}, expected {{{EXPECTED_MAJORS[package]}}}"
                )
    for lock, package, peer in NODE_WRAPPER_PEERS:
        lock_text = (root / lock).read_text(encoding="utf-8")
        ranges = pnpm_lock_peer_ranges(lock_text, package, peer)
        if not ranges:
            problems.append(f"{lock} has no packages entry for {package}")
        for version, peer_range in ranges.items():
            if not peer_range:
                problems.append(f"{lock}: {package}@{version} declares no peer dependency on {peer}")
            elif not npm_admits(peer_range, EXPECTED_MAJORS[peer]):
                problems.append(
                    f"{package}@{version} requires {peer} {peer_range!r}, which excludes major {EXPECTED_MAJORS[peer]}. {MIGRATION_HINT}"
                )
    return problems


def check_python(root: Path) -> list[str]:
    problems = []
    for manifest, package, lock in PYTHON_PINS:
        text = (root / manifest).read_text(encoding="utf-8")
        expected = EXPECTED_MAJORS[package]
        if manifest.endswith("pyproject.toml"):
            data = tomllib.loads(text)
            spec = next((d for d in data["project"]["dependencies"] if _named(package).match(d)), None)
            extra = [
                c
                for c in data.get("tool", {}).get("uv", {}).get("constraint-dependencies", [])
                if _named(package).match(c)
            ]
            cap_home = "[tool.uv] constraint-dependencies"
        else:
            lines = requirements_lines(text)
            spec = next((line for line in lines if _named(package).match(line)), None)
            extra = []
            for line in lines:
                if line.startswith("-c "):
                    constraints = (root / manifest).parent / line.split(None, 1)[1]
                    extra += [
                        c
                        for c in requirements_lines(constraints.read_text(encoding="utf-8"))
                        if _named(package).match(c)
                    ]
            cap_home = "a constraints file"
        if spec is None:
            problems.append(f"{manifest} no longer declares {package}")
            continue
        if python_floor_major(spec) != expected:
            problems.append(f"{manifest}: {package} declares {spec!r}, expected major {expected}. {MIGRATION_HINT}")
        if not python_capped_at(expected, spec, *extra):
            problems.append(
                f"{manifest}: {package} {spec!r} can reach major {expected + 1}; the upper bound belongs in {cap_home}"
            )
        if lock and _lock_package_major(root / lock, package) != expected:
            problems.append(f"{lock} resolves {package} outside major {expected}")
    return problems


def check_rust(root: Path) -> list[str]:
    problems = []
    expected = EXPECTED_MAJORS["posthog-rs"]
    for manifest, table, lock in RUST_PINS:
        data = tomllib.loads((root / manifest).read_text(encoding="utf-8"))
        for key in table:
            data = data[key]
        dependency = data["posthog-rs"]
        requirement = dependency if isinstance(dependency, str) else dependency["version"]
        try:
            major = cargo_requirement_major(requirement)
        except ValueError as err:
            problems.append(f"{manifest}: {err}")
            continue
        if major != expected:
            problems.append(f"{manifest}: posthog-rs = {requirement!r}, expected major {expected}. {MIGRATION_HINT}")
        if _lock_package_major(root / lock, "posthog-rs") != expected:
            problems.append(f"{lock} resolves posthog-rs outside major {expected}")
    return problems


def check_go(root: Path) -> list[str]:
    problems = []
    expected = EXPECTED_MAJORS["posthog-go"]
    # A Go major is a new module path: v1 has no suffix, every later major carries /vN.
    expected_suffix = "" if expected == 1 else f"/v{expected}"
    requires = re.findall(
        rf"^\s*{re.escape(GO_MODULE)}(/v\d+)?\s+(v\d+)", (root / GO_MANIFEST).read_text(encoding="utf-8"), re.MULTILINE
    )
    if not requires:
        problems.append(f"{GO_MANIFEST} no longer requires posthog-go")
    for suffix, version in requires:
        if suffix != expected_suffix or _major(version) != expected:
            problems.append(
                f"{GO_MANIFEST} requires {GO_MODULE}{suffix} {version}, expected {GO_MODULE}{expected_suffix} v{expected}. {MIGRATION_HINT}"
            )
    sums = re.findall(
        rf"^{re.escape(GO_MODULE)}(/v\d+)? (v\d+)", (root / GO_SUM).read_text(encoding="utf-8"), re.MULTILINE
    )
    if not sums or any(suffix != expected_suffix or _major(version) != expected for suffix, version in sums):
        problems.append(f"{GO_SUM} records posthog-go outside {GO_MODULE}{expected_suffix} v{expected}")
    return problems


def check_all(root: Path) -> list[str]:
    return check_node(root) + check_python(root) + check_rust(root) + check_go(root)


def main() -> int:
    problems = check_all(REPO_ROOT)
    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        print(f"\n{len(problems)} SDK major-version problem(s). {MIGRATION_HINT}")
        return 1
    print("Every PostHog SDK is on its expected major.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
