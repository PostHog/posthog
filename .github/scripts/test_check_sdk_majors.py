import json
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("check_sdk_majors.py")
spec = importlib.util.spec_from_file_location("check_sdk_majors", SCRIPT)
guard = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(guard)


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
    assert guard.npm_pinned_to(spec, expected) is pinned
    assert guard.npm_admits(spec, expected) is admits


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
    assert guard.python_floor_major(specs[0]) == expected
    assert guard.python_capped_at(expected, *specs) is capped


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
    assert bool(guard._named(package).match(candidate)) is matches


@pytest.mark.parametrize("requirement,major", [("0.27.0", 0), ("^0.27", 0), ("=1.2.3", 1), ("~0.24.0", 0)])
def test_cargo_requirement_major(requirement: str, major: int) -> None:
    assert guard.cargo_requirement_major(requirement) == major


@pytest.mark.parametrize("requirement", ["*", ">=0.27", "0.27, <2", ""])
def test_cargo_requirement_rejects_floating_ranges(requirement: str) -> None:
    with pytest.raises(ValueError):
        guard.cargo_requirement_major(requirement)


def test_npm_manifests_finds_every_sdk_declaration_and_picks_the_workspace(tmp_path: Path) -> None:
    (tmp_path / "products" / "desktop" / "apps" / "code").mkdir(parents=True)
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"posthog-js": "catalog:"}, "peerDependencies": {"@posthog/react": "*"}})
    )
    (tmp_path / "products" / "desktop" / "apps" / "code" / "package.json").write_text(
        json.dumps({"dependencies": {"posthog-node": "^5.54.1"}})
    )
    (tmp_path / "node_modules" / "x" / "package.json").write_text(json.dumps({"dependencies": {"posthog-node": "*"}}))

    found = guard.npm_manifests(tmp_path)

    assert found == [
        ("package.json", "dependencies", "posthog-js", "catalog:"),
        ("package.json", "peerDependencies", "@posthog/react", "*"),
        ("products/desktop/apps/code/package.json", "dependencies", "posthog-node", "^5.54.1"),
    ]
    assert guard.npm_workspace_for("products/desktop/apps/code/package.json") == (
        "products/desktop/pnpm-workspace.yaml",
        "products/desktop/pnpm-lock.yaml",
    )
    assert guard.npm_workspace_for("package.json") == ("pnpm-workspace.yaml", "pnpm-lock.yaml")


def test_pnpm_lock_peer_ranges_returns_every_version() -> None:
    lock = (
        "packages:\n\n"
        "  '@posthog/react@1.9.0':\n    resolution: {integrity: x}\n    peerDependencies:\n      posthog-js: '>=1.257.2'\n\n"
        "  '@posthog/react@1.11.2':\n    resolution: {integrity: y}\n    peerDependencies:\n      posthog-js: ^2.0.0\n\n"
    )
    assert guard.pnpm_lock_peer_ranges(lock, "@posthog/react", "posthog-js") == {
        "1.9.0": ">=1.257.2",
        "1.11.2": "^2.0.0",
    }


GIT_POSTHOG = '{ git = "https://github.com/PostHog/posthog-rs", rev = "abc", version = "1.0.0" }'


def _write_rust_root(root: Path, workspace_dep: str, workspace_lock: list[tuple[str, str]], cli_dep: str) -> None:
    (root / "rust").mkdir()
    (root / "cli").mkdir()
    (root / "rust" / "Cargo.toml").write_text(f"[workspace.dependencies]\n{workspace_dep}\n")
    (root / "rust" / "Cargo.lock").write_text(
        "".join(f'[[package]]\nname = "{name}"\nversion = "{version}"\n\n' for name, version in workspace_lock)
    )
    (root / "cli" / "Cargo.toml").write_text(f"[dependencies]\n{cli_dep}\n")
    (root / "cli" / "Cargo.lock").write_text('[[package]]\nname = "posthog"\nversion = "1.0.0"\n')


@pytest.mark.parametrize(
    "workspace_dep,workspace_lock,problem",
    [
        (f"posthog = {GIT_POSTHOG}", [("posthog", "1.0.0")], None),
        ('posthog = "1.1.0"', [("posthog", "1.1.0")], None),
        ('posthog-rs = "1.1.0"', [("posthog", "1.1.0"), ("posthog-rs", "1.1.0")], None),
        (
            'posthog = { git = "https://github.com/PostHog/posthog-rs", rev = "abc" }',
            [("posthog", "1.0.0")],
            "rust/Cargo.toml: posthog has no version requirement",
        ),
        ('posthog = "2.0.0"', [("posthog", "2.0.0")], "rust/Cargo.toml: posthog = '2.0.0', expected major 1"),
        (
            'posthog-rs = "0.33.1"',
            [("posthog-rs", "0.33.1")],
            "rust/Cargo.toml: posthog-rs = '0.33.1', expected major 1",
        ),
        (
            'posthog = "1.1.0"',
            [("posthog", "1.1.0"), ("posthog-rs", "0.33.1")],
            "rust/Cargo.lock resolves posthog/posthog-rs to majors [0, 1]",
        ),
        ('serde = "1"', [("serde", "1.0.0")], "rust/Cargo.toml declares neither of posthog, posthog-rs"),
    ],
)
def test_check_rust_reads_either_crate_name_and_every_lock_entry(
    tmp_path: Path, workspace_dep: str, workspace_lock: list[tuple[str, str]], problem: str | None
) -> None:
    _write_rust_root(tmp_path, workspace_dep, workspace_lock, f"posthog = {GIT_POSTHOG}")

    problems = guard.check_rust(tmp_path)

    if problem is None:
        assert problems == []
    else:
        assert len(problems) >= 1
        assert problems[0].startswith(problem)


def test_check_rust_applies_the_expected_major_to_the_cli(tmp_path: Path) -> None:
    _write_rust_root(
        tmp_path, f"posthog = {GIT_POSTHOG}", [("posthog", "1.0.0")], 'posthog-rs = { version = "=0.30.0" }'
    )

    assert guard.check_rust(tmp_path) == [
        "cli/Cargo.toml: posthog-rs = '=0.30.0', expected major 1. " + guard.MIGRATION_HINT,
    ]
