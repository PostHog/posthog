"""Guard: every PostHog SDK this repo installs stays on the major it was migrated to.

A new SDK major removes legacy capture and changes the capture API, so taking one is a
reviewed migration, never a routine bump. The SDK release bots rewrite these manifests
on every release, so the declared spec alone cannot hold the line: this checks every
manifest that names an SDK, the resolved lockfile versions, and the SDK range each
wrapper package accepts.

To take a major on purpose, raise its entry in EXPECTED_MAJORS in the PR that moves the
call sites.
"""

import re
import json
import tomllib
from pathlib import Path
from typing import NamedTuple

import pytest

REPO_ROOT = Path(__file__).parents[3]
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
NPM_LOCKS = ("pnpm-lock.yaml", "products/desktop/pnpm-lock.yaml")
NPM_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")

MIGRATION_HINT = "A new SDK major needs a migration PR; raise EXPECTED_MAJORS there."


class MajorRange(NamedTuple):
    low: int
    high: int | None  # inclusive; None means no upper bound


def _major(version: str) -> int:
    match = re.match(r"v?(\d+)", version)
    assert match, f"cannot read a major from {version!r}"
    return int(match.group(1))


def _is_next_major_boundary(version: str, major: int) -> bool:
    """True for a version that is exactly the first release of major + 1, such as 8, 8.0 or 8.0.0."""
    return re.fullmatch(rf"v?{major + 1}(\.0)*(-0)?", version) is not None


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


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


def pnpm_catalog() -> dict[str, str]:
    catalog: dict[str, str] = {}
    in_catalog = False
    for line in _read("pnpm-workspace.yaml").splitlines():
        if line.startswith("catalog:"):
            in_catalog = True
            continue
        if in_catalog and line and not line.startswith(" "):
            break
        match = re.match(r"^\s+'?([^':\s]+)'?:\s*'?([^'#]+?)'?\s*(#.*)?$", line) if in_catalog else None
        if match:
            catalog[match.group(1)] = match.group(2)
    return catalog


def pnpm_lock_majors(lock: str, package: str) -> set[int]:
    pattern = re.compile(rf"^  '?{re.escape(package)}@(\d+)\.", re.MULTILINE)
    return {int(m.group(1)) for m in pattern.finditer(_read(lock))}


def pnpm_lock_peer_ranges(lock: str, package: str, peer: str) -> dict[str, str]:
    """Every version of `package` in the lock's packages section, with the range it declares on `peer`."""
    entries = re.finditer(rf"^  '{re.escape(package)}@([^(']+)':\n((?:    .*\n)+)", _read(lock), re.MULTILINE)
    ranges = {}
    for entry in entries:
        peer_line = re.search(rf"^      '?{re.escape(peer)}'?:\s*'?([^'\n]+?)'?$", entry.group(2), re.MULTILINE)
        assert peer_line, f"{lock}: {package}@{entry.group(1)} declares no peer dependency on {peer}"
        ranges[entry.group(1)] = peer_line.group(1)
    assert ranges, f"{lock} has no packages entry for {package}"
    return ranges


def npm_manifests() -> list[tuple[str, str, str, str]]:
    """Every (manifest, section, package, lockfile) in the repo that names an npm SDK."""
    found = []
    for path in sorted(REPO_ROOT.rglob("package.json")):
        if SKIPPED_DIRS.intersection(path.parts):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        manifest = path.relative_to(REPO_ROOT).as_posix()
        lock = NPM_LOCKS[1] if manifest.startswith("products/desktop/") else NPM_LOCKS[0]
        for section in NPM_SECTIONS:
            for package in NPM_SDKS:
                if isinstance(data.get(section), dict) and package in data[section]:
                    found.append((manifest, section, package, lock))
    return found


@pytest.mark.parametrize("manifest,section,package,lock", npm_manifests())
def test_node_sdk_stays_on_its_major(manifest: str, section: str, package: str, lock: str) -> None:
    expected = EXPECTED_MAJORS[package]
    spec = json.loads(_read(manifest))[section][package]
    if spec == "catalog:":
        spec = pnpm_catalog()[package]
    assert npm_pinned_to(spec, expected), (
        f"{manifest}: {package} declares {spec!r}, which is not pinned to major {expected}. {MIGRATION_HINT}"
    )


@pytest.mark.parametrize("package", NPM_SDKS)
def test_node_catalog_stays_on_its_major(package: str) -> None:
    spec = pnpm_catalog().get(package)
    if spec is None:
        pytest.skip(f"{package} is not in the pnpm catalog")
    expected = EXPECTED_MAJORS[package]
    assert npm_pinned_to(spec, expected), (
        f"pnpm-workspace.yaml catalog: {package} is {spec!r}, expected major {expected}"
    )


@pytest.mark.parametrize("lock", NPM_LOCKS)
@pytest.mark.parametrize("package", NPM_SDKS)
def test_node_lockfile_resolves_one_major(lock: str, package: str) -> None:
    resolved = pnpm_lock_majors(lock, package)
    if not resolved:
        pytest.skip(f"{package} is not in {lock}")
    expected = EXPECTED_MAJORS[package]
    assert resolved == {expected}, f"{lock} resolves {package} to majors {sorted(resolved)}, expected {{{expected}}}"


# Wrapper packages that depend on an SDK. A routine wrapper release can raise its peer
# range to the next SDK major, which is the same breaking change through a side door.
NODE_WRAPPER_PEERS = [
    ("pnpm-lock.yaml", "@posthog/react", "posthog-js"),
    ("pnpm-lock.yaml", "@posthog/mcp", "posthog-node"),
]


@pytest.mark.parametrize("lock,package,peer", NODE_WRAPPER_PEERS)
def test_node_wrapper_accepts_the_pinned_sdk_major(lock: str, package: str, peer: str) -> None:
    expected = EXPECTED_MAJORS[peer]
    for version, peer_range in pnpm_lock_peer_ranges(lock, package, peer).items():
        assert npm_admits(peer_range, expected), (
            f"{package}@{version} requires {peer} {peer_range!r}, which excludes major {expected}. {MIGRATION_HINT}"
        )


def pep440_clauses(spec: str) -> list[tuple[str, str]]:
    body = re.sub(r"^[A-Za-z0-9_.-]+(\[[^\]]*\])?", "", spec.strip())
    return [(m.group(1), m.group(2)) for m in re.finditer(r"(===|==|~=|!=|<=|>=|<|>)\s*([0-9][0-9A-Za-z.*+!-]*)", body)]


def python_floor_major(spec: str) -> int:
    floors = [_major(v) for op, v in pep440_clauses(spec) if op in ("==", "===", "~=", ">=", ">")]
    assert floors, f"{spec!r} has no lower bound"
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


def uv_constraints(pyproject: str, package: str) -> list[str]:
    constraints = tomllib.loads(_read(pyproject)).get("tool", {}).get("uv", {}).get("constraint-dependencies", [])
    return [c for c in constraints if _named(package).match(c)]


def project_dependency(pyproject: str, package: str) -> str:
    deps = tomllib.loads(_read(pyproject))["project"]["dependencies"]
    return next(d for d in deps if _named(package).match(d))


def requirements_lines(path: str) -> list[str]:
    return [line.strip() for line in _read(path).splitlines() if line.strip() and not line.startswith("#")]


def uv_lock_major(lock: str, package: str) -> int:
    packages = tomllib.loads(_read(lock))["package"]
    return _major(next(p["version"] for p in packages if p["name"] == package))


PYTHON_PINS = [
    ("pyproject.toml", "posthoganalytics", "uv.lock", "uv-constraint"),
    ("services/llm-gateway/pyproject.toml", "posthoganalytics", "services/llm-gateway/uv.lock", "uv-constraint"),
    ("common/ingestion/acceptance_tests/requirements.txt", "posthoganalytics", None, "spec"),
    ("tools/infra-scripts/clitools/requirements.txt", "posthog", None, "constraints-file"),
]


@pytest.mark.parametrize("manifest,package,lock,cap", PYTHON_PINS)
def test_python_sdk_stays_on_its_major(manifest: str, package: str, lock: str | None, cap: str) -> None:
    expected = EXPECTED_MAJORS[package]
    if manifest.endswith("pyproject.toml"):
        spec = project_dependency(manifest, package)
        extra = uv_constraints(manifest, package)
    else:
        lines = requirements_lines(manifest)
        spec = next(line for line in lines if _named(package).match(line))
        constraint_files = [line.split(None, 1)[1] for line in lines if line.startswith("-c ")]
        extra = [
            c
            for f in constraint_files
            for c in requirements_lines(str(Path(manifest).parent / f))
            if _named(package).match(c)
        ]
    assert python_floor_major(spec) == expected, (
        f"{manifest}: {package} declares {spec!r}, expected major {expected}. {MIGRATION_HINT}"
    )
    assert python_capped_at(expected, spec, *extra), (
        f"{manifest}: {package} {spec!r} can reach major {expected + 1}; the upper bound belongs in the {cap}"
    )
    if lock:
        assert uv_lock_major(lock, package) == expected, f"{lock} resolves {package} outside major {expected}"


def cargo_requirement_major(requirement: str) -> int:
    """Cargo treats a bare version as a caret, so `0.27.0` admits only 0.27.x."""
    assert not re.search(r"[*<>,]", requirement) and requirement.strip(), (
        f"{requirement!r} is not a caret, tilde or exact requirement, so it can float across majors"
    )
    return _major(requirement.lstrip("^~="))


def cargo_lock_major(lock: str, package: str) -> int:
    packages = tomllib.loads(_read(lock))["package"]
    return _major(next(p["version"] for p in packages if p["name"] == package))


RUST_PINS = [
    ("rust/Cargo.toml", ("workspace", "dependencies"), "rust/Cargo.lock"),
    ("cli/Cargo.toml", ("dependencies",), "cli/Cargo.lock"),
]


@pytest.mark.parametrize("manifest,table,lock", RUST_PINS)
def test_rust_sdk_stays_on_its_major(manifest: str, table: tuple[str, ...], lock: str) -> None:
    expected = EXPECTED_MAJORS["posthog-rs"]
    data = tomllib.loads(_read(manifest))
    for key in table:
        data = data[key]
    dependency = data["posthog-rs"]
    requirement = dependency if isinstance(dependency, str) else dependency["version"]
    assert cargo_requirement_major(requirement) == expected, (
        f"{manifest}: posthog-rs = {requirement!r}, expected major {expected}. {MIGRATION_HINT}"
    )
    assert cargo_lock_major(lock, "posthog-rs") == expected, f"{lock} resolves posthog-rs outside major {expected}"


GO_MODULE = "github.com/posthog/posthog-go"


def test_go_sdk_stays_on_its_major() -> None:
    expected = EXPECTED_MAJORS["posthog-go"]
    # A Go major is a new module path: v1 has no suffix, every later major carries /vN.
    expected_suffix = "" if expected == 1 else f"/v{expected}"
    module_line = re.compile(rf"^\s*{re.escape(GO_MODULE)}(/v\d+)?\s+(v\d+)", re.MULTILINE)
    requires = module_line.findall(_read("bin/hobby-installer/go.mod"))
    assert requires, "bin/hobby-installer/go.mod no longer requires posthog-go"
    for suffix, version in requires:
        assert suffix == expected_suffix and _major(version) == expected, (
            f"bin/hobby-installer/go.mod requires {GO_MODULE}{suffix} {version}, expected {GO_MODULE}{expected_suffix} v{expected}. {MIGRATION_HINT}"
        )
    sums = re.findall(rf"^{re.escape(GO_MODULE)}(/v\d+)? (v\d+)", _read("bin/hobby-installer/go.sum"), re.MULTILINE)
    assert sums and all(suffix == expected_suffix and _major(version) == expected for suffix, version in sums), (
        f"bin/hobby-installer/go.sum records posthog-go outside {GO_MODULE}{expected_suffix} v{expected}"
    )


@pytest.mark.parametrize(
    "spec,expected,pinned,admits",
    [
        ("5.54.1", 5, True, True),
        ("^5.54.1", 5, True, True),
        ("~5.54.1", 5, True, True),
        ("^0.18.1", 0, True, True),
        (">=5.0.0 <6.0.0", 5, True, True),
        (">=5.0.0 <6.0.0-0", 5, True, True),
        (">=5.0.0 <6.1.0", 5, False, True),
        (">=5.0.0", 5, False, True),
        (">=1.257.2", 1, False, True),
        ("^5.0.0 || ^6.0.0", 5, False, True),
        ("^6.0.0", 5, False, False),
        ("*", 5, False, True),
        ("latest", 5, False, True),
        ("<5", 5, False, False),
        ("<5.0.0-0", 5, False, False),
        (">5", 5, False, False),
        (">5.0.0", 5, False, True),
        (">5.1", 5, False, True),
        (">4 <6", 5, True, True),
    ],
)
def test_npm_range_semantics(spec: str, expected: int, pinned: bool, admits: bool) -> None:
    assert npm_pinned_to(spec, expected) is pinned
    assert npm_admits(spec, expected) is admits


@pytest.mark.parametrize(
    "specs,expected,capped",
    [
        (("posthoganalytics==7.60.1",), 7, True),
        (("posthoganalytics~=7.60",), 7, True),
        (("posthoganalytics>=7.60.1",), 7, False),
        (("posthoganalytics>=7.60.1,<8",), 7, True),
        (("posthoganalytics>=7.60.1,<8.0.0",), 7, True),
        (("posthoganalytics>=7.60.1,<8.1",), 7, False),
        (("posthoganalytics>=7.60.1", "posthoganalytics<8"), 7, True),
        (("posthoganalytics>=7.60.1", "posthoganalytics<9"), 7, False),
        (("posthog>=7.60.1", "posthog<=7.99"), 7, True),
        (("posthog>=7.60.1", "posthog<=8"), 7, False),
    ],
)
def test_python_cap_semantics(specs: tuple[str, ...], expected: int, capped: bool) -> None:
    assert python_floor_major(specs[0]) == expected
    assert python_capped_at(expected, *specs) is capped


@pytest.mark.parametrize(
    "package,candidate,matches",
    [
        ("posthog", "posthog<8", True),
        ("posthog", "posthog[extra]>=7", True),
        ("posthog", "posthoganalytics<8", False),
        ("posthoganalytics", "posthoganalytics>=7.60.1", True),
    ],
)
def test_python_constraint_names_match_exactly(package: str, candidate: str, matches: bool) -> None:
    assert bool(_named(package).match(candidate)) is matches
