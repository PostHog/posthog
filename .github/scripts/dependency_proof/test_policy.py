from datetime import UTC, datetime

import pytest

from dependency_proof import policy
from dependency_proof.policy import DirectChange, Refused

NOW = datetime(2026, 11, 9, tzinfo=UTC)


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        ("^1.2.3", "^1.3.0", None),
        ("~1.2.3", "~1.2.4", None),
        ("1.2.3", "1.2.4", None),
        ("^0.3.1", "^0.3.2", None),
        ("^1.2.3", "^2.0.0", "major change"),
        ("^0.3.1", "^0.4.0", "0.x minor change"),
        ("^1.2.3", "~1.2.3", "changes the range operator"),
        ("^1.2.3", "github:foo/bar", "not a plain registry"),
        ("^1.2.3", "npm:other@^1.2.3", "not a plain registry"),
        ("^1.2.3", "https://example.com/pkg.tgz", "not a plain registry"),
        ("workspace:*", "workspace:^", "not a plain registry"),
        ("^1.2.3", "file:../pkg", "not a plain registry"),
        ("^1.2.3", "link:../pkg", "not a plain registry"),
        ("^1.2.3", "^1.2.4-beta.1", "not a plain registry"),
        ("^1.2.3", ">=1.2.3", "not a plain registry"),
        ("^1.2.3", "^1.2.4\n", "not a plain registry"),
        ("^1.20.3", "^1.2.3", "not an upgrade"),
        ("^1.2.3", "^1.2.2", "not an upgrade"),
        ("^0.0.3", "^0.0.9", "0.0.x change"),
    ],
)
def test_check_bump(old: str, new: str, reason: str | None) -> None:
    if reason is None:
        policy.check_bump("x", old, new)
    else:
        with pytest.raises(Refused, match=reason):
            policy.check_bump("x", old, new)


@pytest.mark.parametrize(
    ("head", "reason"),
    [
        ({"dependencies": {"left-pad": "^1.3.1"}}, None),
        ({"packageManager": "pnpm@11.0.0"}, "more than dependency versions"),
        ({"scripts": {"postinstall": "node x"}}, "more than dependency versions"),
        ({"engines": {"node": ">=26"}}, "more than dependency versions"),
        ({"pnpm": {"allowBuilds": {"x": True}}}, "more than dependency versions"),
        ({"exports": {"require": "./a.cjs", "import": "./a.mjs"}}, "more than dependency versions"),
        ({"private": 1}, "more than dependency versions"),
        ({"dependencies": {"left-pad": "^1.3.0", "extra": "^1.0.0"}}, "adds or removes"),
        ({"dependencies": {}}, "adds or removes"),
        ({"devDependencies": {"x": "^1.0.0"}}, "adds or removes"),
        ({"dependencies": {"left-pad": "npm:left-pad@^1.3.1"}}, "not a plain registry"),
    ],
)
def test_check_manifest(head: dict, reason: str | None) -> None:
    base = {
        "private": True,
        "exports": {"import": "./a.mjs", "require": "./a.cjs"},
        "dependencies": {"left-pad": "^1.3.0"},
    }
    head = {**base, **head}
    if reason is None:
        policy.check_manifest("package.json", base, head)
    else:
        with pytest.raises(Refused, match=reason):
            policy.check_manifest("package.json", base, head)


WORKSPACE = {
    "packages": ["."],
    "allowBuilds": {"esbuild": True},
    "minimumReleaseAge": "10080",
    "catalog": {"kea": "^4.0.0", "typescript": "6.0.3"},
}


@pytest.mark.parametrize(
    ("default", "base", "head", "expected"),
    [
        ({}, {}, {"catalog": {"kea": "^4.0.1", "typescript": "6.0.3"}}, ["kea"]),
        ({}, {}, {}, []),
        ({"catalog": {"kea": "^4.0.0", "typescript": "6.0.4"}}, {}, {}, []),
        ({"minimumReleaseAge": "20160"}, {}, {"minimumReleaseAge": "20160"}, "does not set minimumReleaseAge"),
        ({}, {}, {"catalog": {"kea": "~4.0.1", "typescript": "6.0.3"}}, "changes the range operator"),
        ({}, {}, {"catalog": {"kea": "^5.0.0", "typescript": "6.0.3"}}, "major change"),
        ({}, {}, {"catalog": {"kea": "^4.0.0", "typescript": "6.0.2"}}, "not an upgrade"),
        ({}, {}, {"catalog": {"kea": "^4.0.0"}}, "adds or removes a package in catalog"),
        (
            {},
            {},
            {"catalog": {"kea": "^4.0.0", "typescript": "6.0.3", "left-pad": "^1.3.0"}},
            "adds or removes a package in catalog",
        ),
    ],
)
def test_check_workspace(default: dict, base: dict, head: dict, expected: list[str] | str) -> None:
    files = [{**WORKSPACE, **changes} for changes in (default, base, head)]
    if isinstance(expected, list):
        assert policy.check_workspace("pnpm-workspace.yaml", *files) == expected
    else:
        with pytest.raises(Refused, match=expected):
            policy.check_workspace("pnpm-workspace.yaml", *files)


WORKSPACE_TEXT = b"""packages:
    - .
catalog:
    # state
    kea: ^4.0.0
    '@posthog/icons': 0.39.0
catalogs:
    next:
        kea: ^5.0.0
minimumReleaseAge: 10080
"""


@pytest.mark.parametrize(
    ("side", "old", "new", "refused"),
    [
        ("head", b"kea: ^4.0.0", b"kea: ^4.0.1", False),
        ("head", b"'@posthog/icons': 0.39.0", b"'@posthog/icons': 0.39.1", False),
        ("default", b"kea: ^4.0.0", b"kea: ^4.0.1", False),
        ("head", b"minimumReleaseAge: 10080", b"minimumReleaseAge: 1", True),
        ("head", b"kea: ^5.0.0", b"kea: ^5.0.1", True),
        ("head", b"    - .", b"    - |\n        .", True),
        ("head", b"# state", b"left-pad: ^1.3.0", True),
        ("head", b"kea: ^4.0.0", b"koa: ^4.0.0", True),
        ("head", b"kea: ^4.0.0", b'kea: "^4.0.1 "', True),
        ("head", b"10080\n", b"10080\n\ntrustPolicy: off\n", True),
    ],
)
def test_check_workspace_text(side: str, old: bytes, new: bytes, refused: bool) -> None:
    texts = {"default": WORKSPACE_TEXT, "head": WORKSPACE_TEXT, side: WORKSPACE_TEXT.replace(old, new)}
    assert texts[side] != WORKSPACE_TEXT
    if refused:
        with pytest.raises(Refused, match="differs from the default branch by more than a catalog version"):
            policy.check_workspace_text("pnpm-workspace.yaml", texts["default"], texts["head"])
    else:
        policy.check_workspace_text("pnpm-workspace.yaml", texts["default"], texts["head"])


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ([("M", "pnpm-lock.yaml"), ("M", "frontend/package.json")], None),
        ([("M", "products/desktop/pnpm-lock.yaml")], None),
        ([("M", "pnpm-workspace.yaml"), ("M", "pnpm-lock.yaml")], None),
        ([("M", ".npmrc")], "not a manifest, a lockfile or a workspace file"),
        ([("M", ".github/renovate.json5")], "not a manifest, a lockfile or a workspace file"),
        ([("M", "patches/left-pad@1.3.0.patch")], "not a manifest, a lockfile or a workspace file"),
        ([("M", "package-lock.json")], "not a manifest, a lockfile or a workspace file"),
        ([("A", "package.json")], "not a modification"),
        ([("D", "pnpm-lock.yaml")], "not a modification"),
        ([("M", "a/../package.json")], "name this proof does not accept"),
        ([("M", "a b/package.json")], "name this proof does not accept"),
        ([], "changes no files"),
    ],
)
def test_eligible_paths(changes: list[tuple[str, str]], reason: str | None) -> None:
    if reason is None:
        assert policy.eligible_paths(changes) == sorted(path for _, path in changes)
    else:
        with pytest.raises(Refused, match=reason):
            policy.eligible_paths(changes)


BLOCKED = policy.blocked_patterns(
    {
        "allowBuilds": {"esbuild": True, "@datadog/pprof": False, "node-gyp@<10": True},
        "onlyBuiltDependencies": ["sharp"],
        "neverBuiltDependencies": "fsevents",
        "minimumReleaseAgeExclude": ["posthog-js", "@posthog/*", "kea@4.0.0-pre.6"],
        "trustPolicyExclude": ["semver@5.7.2 || 6.3.1"],
    },
    {"pnpm": {"ignoredBuiltDependencies": ["core-js"]}},
    '["lmdb"]',
)


@pytest.mark.parametrize(
    ("spec", "setting"),
    [
        ("esbuild", "allowBuilds"),
        ("esbuild@0.25.0", "allowBuilds"),
        ("@datadog/pprof", None),
        ("node-gyp@11.0.0", "allowBuilds"),
        ("sharp", "onlyBuiltDependencies"),
        ("fsevents", "neverBuiltDependencies"),
        ("core-js", "ignoredBuiltDependencies"),
        ("lmdb", "onlyBuiltDependenciesFile"),
        ("posthog-js", "minimumReleaseAgeExclude"),
        ("@posthog/icons@0.39.1", "minimumReleaseAgeExclude"),
        ("kea@4.0.1", "minimumReleaseAgeExclude"),
        ("semver", "trustPolicyExclude"),
        ("semver@6.3.1", "trustPolicyExclude"),
        ("semver@6.3.1(peer@1.0.0)", "trustPolicyExclude"),
        ("semver@7.7.3", None),
        ("left-pad", None),
        ("esbuild-wasm", None),
    ],
)
def test_blocked_reason(spec: str, setting: str | None) -> None:
    reason = policy.blocked_reason(spec, BLOCKED)
    assert reason == (None if setting is None else f"{policy.package_name(spec)} is named in {setting}")


@pytest.mark.parametrize("pattern", ["!left-pad", "/^left-/", "/left.*/", "@scope/{one,two}", "left-pa?", "[l]eft-pad"])
def test_blocked_reason_refuses_patterns_it_cannot_read(pattern: str) -> None:
    with pytest.raises(Refused, match="pattern this proof does not read"):
        policy.blocked_reason("left-pad", {"minimumReleaseAgeExclude": [pattern]})


def test_a_setting_that_allows_every_build_blocks_every_package() -> None:
    patterns = policy.blocked_patterns({}, {"pnpm": {"dangerouslyAllowAllBuilds": True}}, None)
    assert policy.blocked_reason("@scope/left-pad@1.3.1", patterns) == (
        "@scope/left-pad is named in dangerouslyAllowAllBuilds"
    )


@pytest.mark.parametrize(
    ("metadata", "reason"),
    [
        ({"time": {"1.0.0": "2026-11-01T00:00:00.000Z"}}, None),
        ({"time": {"1.0.0": "2026-11-02T00:00:00.000Z"}}, None),
        ({"time": {"1.0.0": "2026-11-03T00:00:00.000Z"}}, "published 6 day"),
        ({"time": {"1.0.0": "2026-11-08T23:00:00.000Z"}}, "published 0 day"),
        ({"time": {"0.9.0": "2026-01-01T00:00:00.000Z"}}, "no publish time"),
        ({}, "no publish time"),
        ({"time": {"1.0.0": "yesterday"}}, "unreadable publish time"),
        ({"time": {"1.0.0": "2026-11-01T00:00:00"}}, "unreadable publish time"),
    ],
)
def test_release_age_reason(metadata: dict, reason: str | None) -> None:
    found = policy.release_age_reason("pkg", "1.0.0", metadata, NOW)
    assert found == reason if reason is None else reason in found


def importers(
    specifier: str,
    version: str,
    peer: str = "18.3.1",
    extra: dict | None = None,
    catalog: str = "^4.0.0",
    kea: str = "4.0.0",
) -> dict:
    deps = {
        "left-pad": {"specifier": specifier, "version": version},
        "react-dom": {"specifier": "^18.0.0", "version": f"18.3.0(react@{peer})"},
        "kea": {"specifier": "catalog:", "version": kea},
        **(extra or {}),
    }
    return {"catalogs": {"default": {"kea": {"specifier": catalog}}}, "importers": {".": {"dependencies": deps}}}


BASE_LOCK = importers("^1.3.0", "1.3.0", peer="18.3.0")
PEER_ONLY_CHANGE = DirectChange(name="react-dom", old="18.3.0", new="18.3.0", range_changed=False)


@pytest.mark.parametrize(
    ("head_lock", "expected", "reason"),
    [
        (
            importers("^1.3.0", "1.3.1"),
            [DirectChange(name="left-pad", old="1.3.0", new="1.3.1", range_changed=False), PEER_ONLY_CHANGE],
            None,
        ),
        (
            importers("^1.3.1", "1.3.1", peer="18.3.0"),
            [DirectChange(name="left-pad", old="1.3.0", new="1.3.1", range_changed=True)],
            None,
        ),
        (
            importers("^1.3.1", "1.3.0", peer="18.3.0"),
            [DirectChange(name="left-pad", old="1.3.0", new="1.3.0", range_changed=True)],
            None,
        ),
        (
            importers("^1.3.0", "1.3.0", peer="18.3.0", catalog="^4.0.1", kea="4.0.1"),
            [DirectChange(name="kea", old="4.0.0", new="4.0.1", range_changed=True)],
            None,
        ),
        (
            importers("^1.3.0", "1.3.0", peer="18.3.0", kea="4.0.1"),
            [DirectChange(name="kea", old="4.0.0", new="4.0.1", range_changed=False)],
            None,
        ),
        (
            importers("^1.3.0", "1.3.0", peer="18.3.0", catalog="^4.0.1"),
            [DirectChange(name="kea", old="4.0.0", new="4.0.0", range_changed=True)],
            None,
        ),
        (importers("^1.3.0", "left-pad@1.3.1"), None, "not a plain registry"),
        (importers("^1.3.0", "2.0.0"), None, "major change"),
        ({"importers": {".": {}, "frontend": {}}}, None, "adds or removes a workspace project"),
        (
            importers("^1.3.0", "1.3.0", extra={"extra": {"specifier": "^1.0.0", "version": "1.0.0"}}),
            None,
            "adds or removes",
        ),
    ],
)
def test_direct_changes(head_lock: dict, expected: list | None, reason: str | None) -> None:
    if reason is None:
        assert policy.direct_changes(BASE_LOCK, head_lock) == expected
    else:
        with pytest.raises(Refused, match=reason):
            policy.direct_changes(BASE_LOCK, head_lock)


@pytest.mark.parametrize(
    ("resolution", "reason"),
    [
        ({"integrity": "sha512-b"}, None),
        (
            {"integrity": "sha512-b", "tarball": "https://example.com/left-pad.tgz"},
            "does not resolve from the registry",
        ),
        (
            {"type": "git", "repo": "https://example.com/x.git", "commit": "deadbeef"},
            "does not resolve from the registry",
        ),
        ({"type": "directory", "directory": "vendor/left-pad"}, "does not resolve from the registry"),
    ],
)
def test_new_packages(resolution: dict, reason: str | None) -> None:
    base = {"packages": {"left-pad@1.3.0": {"resolution": {"integrity": "sha512-a"}}}}
    head = {"packages": {**base["packages"], "left-pad@1.3.1": {"resolution": resolution}}}
    if reason is None:
        assert policy.new_packages(base, head) == ["left-pad@1.3.1"]
    else:
        with pytest.raises(Refused, match=reason):
            policy.new_packages(base, head)


ROOT_LOCK = {"importers": {".": {}, "frontend": {}}}
DESKTOP_LOCK = {"importers": {".": {}, "apps/code": {}}}


@pytest.mark.parametrize(
    ("path", "directory", "lock", "member"),
    [
        ("package.json", "", ROOT_LOCK, True),
        ("frontend/package.json", "", ROOT_LOCK, True),
        ("products/desktop/package.json", "", ROOT_LOCK, False),
        ("products/desktop/package.json", "products/desktop", DESKTOP_LOCK, True),
        ("products/desktop/apps/code/package.json", "products/desktop", DESKTOP_LOCK, True),
        ("products/desktop/frontend/package.json", "products/desktop", DESKTOP_LOCK, False),
    ],
)
def test_check_member(path: str, directory: str, lock: dict, member: bool) -> None:
    if member:
        policy.check_member(path, directory, lock)
    else:
        with pytest.raises(Refused, match="is not a project of"):
            policy.check_member(path, directory, lock)


def test_lockfile_dir() -> None:
    lockfiles = {"pnpm-lock.yaml", "products/desktop/pnpm-lock.yaml"}
    assert policy.lockfile_dir("frontend/package.json", lockfiles.__contains__) == ""
    assert policy.lockfile_dir("products/desktop/apps/x/package.json", lockfiles.__contains__) == "products/desktop"
    assert policy.lockfile_dir("pnpm-lock.yaml", lockfiles.__contains__) == ""
    with pytest.raises(Refused, match="no lockfile above it"):
        policy.lockfile_dir("frontend/package.json", set().__contains__)


def test_settings_paths() -> None:
    assert policy.settings_paths("", {}) == [
        "pnpm-workspace.yaml",
        ".npmrc",
        ".pnpmfile.cjs",
        "pnpmfile.cjs",
    ]
    nested = policy.settings_paths("products/desktop", {"onlyBuiltDependenciesFile": "built.json"})
    assert "products/desktop/pnpm-workspace.yaml" in nested
    assert nested[-1] == "products/desktop/built.json"


@pytest.mark.parametrize(
    ("manifest", "version", "refused"),
    [
        ({"packageManager": "pnpm@11.28.5"}, "11.28.5", None),
        ({"packageManager": "pnpm@10.33.0"}, None, "package.json pins a pnpm older than 11"),
        ({"packageManager": "pnpm@11.28.5+sha512.abc"}, None, "package.json does not pin an exact pnpm version"),
        ({"packageManager": "yarn@4.0.0"}, None, "package.json does not pin an exact pnpm version"),
        ({}, None, "package.json does not pin an exact pnpm version"),
    ],
)
def test_pnpm_version(manifest: dict, version: str | None, refused: str | None) -> None:
    if refused is not None:
        with pytest.raises(Refused, match=refused):
            policy.pnpm_version("package.json", manifest)
    else:
        assert policy.pnpm_version("package.json", manifest) == version


@pytest.mark.parametrize("text", [b'{"a": 1, "a": 2}', b"[]", b"{"])
def test_load_manifest_refuses(text: bytes) -> None:
    with pytest.raises(Refused):
        policy.load_manifest(text)
