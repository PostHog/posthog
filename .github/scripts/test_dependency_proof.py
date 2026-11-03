import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("dependency_proof.py")
spec = importlib.util.spec_from_file_location("dependency_proof", SCRIPT)
proof = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(proof)

MEMBERS = [".", "frontend", "products/*", "!products/desktop", "packages/quill/apps/*"]
WORKSPACE = {
    "allowBuilds": {"esbuild": True, "puppeteer": False},
    "minimumReleaseAgeExclude": ["posthog-js", "@posthog/*", "kea@4.0.0-pre.6"],
    "trustPolicyExclude": ["semver@5.7.2 || 6.3.1"],
}


def _modified(*paths: str) -> list[dict]:
    return [{"filename": path, "status": "modified"} for path in paths]


@pytest.mark.parametrize(
    "files, refused",
    [
        (_modified("pnpm-lock.yaml", "package.json", "frontend/package.json", "products/x/package.json"), False),
        (_modified("pnpm-lock.yaml", "packages/quill/apps/site/package.json"), False),
        (_modified("frontend/package.json"), True),
        (_modified("pnpm-lock.yaml", "products/desktop/package.json"), True),
        (_modified("pnpm-lock.yaml", "products/x/nested/package.json"), True),
        (_modified("pnpm-lock.yaml", "pnpm-workspace.yaml"), True),
        (_modified("products/desktop/pnpm-lock.yaml", "products/desktop/package.json"), True),
        (
            [
                {"filename": "pnpm-lock.yaml", "status": "modified"},
                {"filename": "tools/x/package.json", "status": "added"},
            ],
            True,
        ),
        (_modified(*(["pnpm-lock.yaml"] * proof.COMPARE_FILE_LIMIT)), True),
    ],
)
def test_only_the_root_lockfile_and_workspace_manifests_are_proved(files: list[dict], refused: bool) -> None:
    assert (proof.unprovable_file_reason(files, MEMBERS) is not None) is refused


@pytest.mark.parametrize(
    "before, after, refused",
    [
        ({"dependencies": {"zod": "3.22.0"}}, {"dependencies": {"zod": "3.22.4"}}, False),
        ({"devDependencies": {"zod": "^3.22.0"}}, {"devDependencies": {"zod": "^3.23.0-rc.1"}}, False),
        ({"dependencies": {"zod": "3.22.0"}}, {"dependencies": {"zod": "npm:evil@1.0.0"}}, True),
        ({"dependencies": {"zod": "3.22.0"}}, {"dependencies": {"zod": "github:evil/zod"}}, True),
        ({"dependencies": {"zod": "3.22.0"}}, {"dependencies": {"zod": "https://example.com/zod.tgz"}}, True),
        ({"dependencies": {"zod": "catalog:"}}, {"dependencies": {"zod": "3.22.0"}}, True),
        ({"dependencies": {"zod": "3.22.0"}}, {"dependencies": {"zod": "3.22.0", "left-pad": "1.3.0"}}, True),
        (
            {"dependencies": {"zod": "3.22.0"}},
            {"dependencies": {"zod": "3.22.0"}, "scripts": {"postinstall": "x"}},
            True,
        ),
        ({"packageManager": "pnpm@11.0.0"}, {"packageManager": "pnpm@11.0.1"}, True),
        ({"peerDependencies": {"react": "18.3.1"}}, {"peerDependencies": {"react": "18.3.2"}}, True),
    ],
)
def test_manifests_may_only_bump_registry_versions(before: dict, after: dict, refused: bool) -> None:
    reason = proof.manifest_change_reason("package.json", before, after)
    assert (reason is not None) is refused


def _lock(**packages: dict) -> dict:
    return {"packages": {"zod@3.22.0": {"resolution": {"integrity": "sha512-a"}}, **packages}}


@pytest.mark.parametrize(
    "added, refused",
    [
        ({"zod@3.22.4": {"resolution": {"integrity": "sha512-b"}}}, False),
        ({"puppeteer@24.0.0": {"resolution": {"integrity": "sha512-b"}}}, False),
        ({"esbuild@0.25.1": {"resolution": {"integrity": "sha512-b"}}}, True),
        ({"@posthog/core@1.62.1": {"resolution": {"integrity": "sha512-b"}}}, True),
        ({"semver@6.3.1": {"resolution": {"integrity": "sha512-b"}}}, True),
        ({"zod@3.22.4": {"resolution": {"tarball": "https://example.com/zod.tgz"}}}, True),
        ({"zod@3.22.4": {"resolution": {"integrity": "sha512-b", "tarball": "https://example.com/zod.tgz"}}}, True),
        ({"zod@3.22.4": {"resolution": {"type": "git", "repo": "https://example.com/zod.git", "commit": "abc"}}}, True),
    ],
)
def test_packages_the_update_adds_anywhere_in_the_graph_are_checked(added: dict, refused: bool) -> None:
    reason = proof.added_package_reason(_lock(), _lock(**added), WORKSPACE)
    assert (reason is not None) is refused


@pytest.mark.parametrize(
    "text, loads",
    [
        (b'{"dependencies": {"zod": "3.22.4"}}', True),
        (b'{"dependencies": {"zod": "github:evil/zod", "zod": "3.22.4"}}', False),
    ],
)
def test_a_manifest_that_repeats_a_key_is_not_read(text: bytes, loads: bool) -> None:
    assert (proof.load_manifest(text) is not None) is loads


def test_the_notice_title_survives_workflow_command_escaping() -> None:
    assert proof.escape_property("stamphog attestation: release, 1") == "stamphog attestation%3A release%2C 1"
