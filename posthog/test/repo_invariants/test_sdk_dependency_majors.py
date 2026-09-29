"""Guard: every PostHog SDK this repo installs stays on the major it was migrated to.

A new SDK major removes legacy capture and changes the capture API, so taking one is a
reviewed migration, never a routine bump. The SDK release bots rewrite these manifests
on every release, so the declared spec alone cannot hold the line: this checks the spec,
the resolved lockfile version, and the SDK range each wrapper package accepts.

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

MIGRATION_HINT = "A new SDK major needs a migration PR; raise EXPECTED_MAJORS there."


class MajorRange(NamedTuple):
    low: int
    high: int | None  # inclusive; None means no upper bound


def _majors(version: str) -> int:
    match = re.match(r"v?(\d+)", version)
    assert match, f"cannot read a major from {version!r}"
    return int(match.group(1))


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


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
                major = _majors(token.lstrip("^~="))
                low, high = max(low, major), major if high is None else min(high, major)
            elif token.startswith(">="):
                low = max(low, _majors(token[2:]))
            elif token.startswith(">"):
                low = max(low, _majors(token[1:]))
            elif token.startswith("<="):
                high = _majors(token[2:]) if high is None else min(high, _majors(token[2:]))
            elif token.startswith("<"):
                major = _majors(token[1:])
                cap = major - 1 if re.fullmatch(r"<v?\d+(\.0)*", token) else major
                high = cap if high is None else min(high, cap)
            else:
                major = _majors(token.replace("x", "0"))
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


def pnpm_lock_peer_range(lock: str, package: str, peer: str) -> str:
    """The peer range `package` declares on `peer` in the lock's packages section."""
    entry = re.search(rf"^  '{re.escape(package)}@[^(']+':\n((?:    .*\n)+)", _read(lock), re.MULTILINE)
    assert entry, f"{lock} has no packages entry for {package}"
    peer_line = re.search(rf"^      '?{re.escape(peer)}'?:\s*'?([^'\n]+?)'?$", entry.group(1), re.MULTILINE)
    assert peer_line, f"{lock}: {package} declares no peer dependency on {peer}"
    return peer_line.group(1)


NODE_PINS = [
    ("nodejs/package.json", "dependencies", "posthog-node", "pnpm-lock.yaml"),
    ("services/mcp/package.json", "dependencies", "posthog-node", "pnpm-lock.yaml"),
    ("services/mcp/package.json", "dependencies", "posthog-js-lite", "pnpm-lock.yaml"),
    ("tools/hedgebox-dummy/package.json", "dependencies", "posthog-js", "pnpm-lock.yaml"),
    ("pnpm-workspace.yaml", "catalog", "posthog-js", "pnpm-lock.yaml"),
    ("pnpm-workspace.yaml", "catalog", "@posthog/react", "pnpm-lock.yaml"),
    ("products/desktop/apps/code/package.json", "dependencies", "posthog-node", "products/desktop/pnpm-lock.yaml"),
    (
        "products/desktop/apps/mobile/package.json",
        "dependencies",
        "posthog-react-native",
        "products/desktop/pnpm-lock.yaml",
    ),
    ("products/desktop/packages/ui/package.json", "dependencies", "posthog-js", "products/desktop/pnpm-lock.yaml"),
    (
        "products/desktop/tools/announcements-admin/package.json",
        "dependencies",
        "posthog-js",
        "products/desktop/pnpm-lock.yaml",
    ),
]


@pytest.mark.parametrize("manifest,section,package,lock", NODE_PINS)
def test_node_sdk_stays_on_its_major(manifest: str, section: str, package: str, lock: str) -> None:
    expected = EXPECTED_MAJORS[package]
    if section == "catalog":
        spec = pnpm_catalog()[package]
    else:
        spec = json.loads(_read(manifest))[section][package]
        if spec == "catalog:":
            spec = pnpm_catalog()[package]
    assert npm_pinned_to(spec, expected), (
        f"{manifest}: {package} declares {spec!r}, which is not pinned to major {expected}. {MIGRATION_HINT}"
    )
    resolved = pnpm_lock_majors(lock, package)
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
    peer_range = pnpm_lock_peer_range(lock, package, peer)
    assert npm_admits(peer_range, expected), (
        f"{package} requires {peer} {peer_range!r}, which excludes major {expected}. {MIGRATION_HINT}"
    )


def pep440_clauses(spec: str) -> list[tuple[str, str]]:
    body = re.sub(r"^[A-Za-z0-9_.-]+(\[[^\]]*\])?", "", spec.strip())
    return [(m.group(1), m.group(2)) for m in re.finditer(r"(===|==|~=|!=|<=|>=|<|>)\s*([0-9][0-9A-Za-z.*+!-]*)", body)]


def python_floor_major(spec: str) -> int:
    floors = [_majors(v) for op, v in pep440_clauses(spec) if op in ("==", "===", "~=", ">=", ">")]
    assert floors, f"{spec!r} has no lower bound"
    return max(floors)


def python_capped_at(major: int, *specs: str) -> bool:
    """True when the specs together exclude every version of major + 1."""
    for spec in specs:
        for op, version in pep440_clauses(spec):
            if op in ("==", "===") or op == "~=":
                return True
            if op == "<" and _majors(version) <= major + 1:
                return True
            if op == "<=" and _majors(version) <= major:
                return True
    return False


def uv_constraints(pyproject: str) -> list[str]:
    return tomllib.loads(_read(pyproject)).get("tool", {}).get("uv", {}).get("constraint-dependencies", [])


def project_dependency(pyproject: str, package: str) -> str:
    deps = tomllib.loads(_read(pyproject))["project"]["dependencies"]
    return next(d for d in deps if re.match(rf"{re.escape(package)}(\[|[^A-Za-z0-9_.-])", d))


def requirements_lines(path: str) -> list[str]:
    return [line.strip() for line in _read(path).splitlines() if line.strip() and not line.startswith("#")]


def uv_lock_major(lock: str, package: str) -> int:
    packages = tomllib.loads(_read(lock))["package"]
    return _majors(next(p["version"] for p in packages if p["name"] == package))


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
        extra = [c for c in uv_constraints(manifest) if c.startswith(package)]
    else:
        lines = requirements_lines(manifest)
        spec = next(line for line in lines if re.match(rf"{re.escape(package)}([^A-Za-z0-9_.-]|$)", line))
        constraint_files = [line.split(None, 1)[1] for line in lines if line.startswith("-c ")]
        extra = [
            c
            for f in constraint_files
            for c in requirements_lines(str(Path(manifest).parent / f))
            if c.startswith(package)
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
    return _majors(requirement.lstrip("^~="))


def cargo_lock_major(lock: str, package: str) -> int:
    packages = tomllib.loads(_read(lock))["package"]
    return _majors(next(p["version"] for p in packages if p["name"] == package))


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
    requires = re.findall(
        rf"^\s*{re.escape(GO_MODULE)}(/v\d+)?\s+(v\d+)", _read("bin/hobby-installer/go.mod"), re.MULTILINE
    )
    assert requires, "bin/hobby-installer/go.mod no longer requires posthog-go"
    for suffix, version in requires:
        # A Go major is a new module path, so the suffix is the pin and the version confirms it.
        assert suffix == "" and _majors(version) == expected, (
            f"bin/hobby-installer/go.mod requires {GO_MODULE}{suffix} {version}, expected major {expected}. {MIGRATION_HINT}"
        )
    sums = re.findall(rf"^{re.escape(GO_MODULE)}(/v\d+)? (v\d+)", _read("bin/hobby-installer/go.sum"), re.MULTILINE)
    assert sums and all(suffix == "" and _majors(version) == expected for suffix, version in sums), (
        f"bin/hobby-installer/go.sum records posthog-go outside major {expected}"
    )


@pytest.mark.parametrize(
    "spec,expected,pinned,admits",
    [
        ("5.54.1", 5, True, True),
        ("^5.54.1", 5, True, True),
        ("~5.54.1", 5, True, True),
        ("^0.18.1", 0, True, True),
        (">=5.0.0 <6.0.0", 5, True, True),
        (">=5.0.0", 5, False, True),
        (">=1.257.2", 1, False, True),
        ("^5.0.0 || ^6.0.0", 5, False, True),
        ("^6.0.0", 5, False, False),
        ("*", 5, False, True),
        ("latest", 5, False, True),
        ("<5", 5, False, False),
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
        (("posthoganalytics>=7.60.1", "posthoganalytics<8"), 7, True),
        (("posthoganalytics>=7.60.1", "posthoganalytics<9"), 7, False),
        (("posthog>=7.60.1", "posthog<=7.99"), 7, True),
    ],
)
def test_python_cap_semantics(specs: tuple[str, ...], expected: int, capped: bool) -> None:
    assert python_floor_major(specs[0]) == expected
    assert python_capped_at(expected, *specs) is capped
