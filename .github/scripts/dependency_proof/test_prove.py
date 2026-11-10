import os
import json
import stat
import hashlib
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dependency_proof import prove as prover
from dependency_proof.policy import RENOVATE_BOT_USER_ID, Refused

REPO_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY = "PostHog/posthog"
HEAD, MERGE_BASE, WORKFLOW_SHA = "a" * 40, "b" * 40, "c" * 40
NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)
WORKSPACE = b"packages:\n    - '.'\nminimumReleaseAge: 10080\nminimumReleaseAgeExclude:\n    - posthog-js\n    - '@posthog/*'\nallowBuilds:\n    esbuild: true\n"
PROVER = ".github/scripts/dependency_proof/prove.py"
RENOVATE = b"{ packageRules: [ { matchPackageNames: ['posthog-js'], minimumReleaseAge: null, }, ], }"


def manifest(name: str, version_range: str) -> bytes:
    return json.dumps(
        {"name": "root", "packageManager": "pnpm@11.28.5", "dependencies": {name: version_range}}
    ).encode()


def lockfile(name: str, specifier: str, version: str, integrity: str = "sha512-x", deprecated: bool = False) -> bytes:
    deprecation = "    deprecated: use something else\n" if deprecated else ""
    return (
        f"lockfileVersion: '9.0'\n\nimporters:\n\n  .:\n    dependencies:\n      {name}:\n        specifier: {specifier}\n"
        f"        version: {version}\n\npackages:\n\n  {name}@{version}:\n    resolution: {{integrity: {integrity}}}\n"
        f"{deprecation}\nsnapshots:\n\n  {name}@{version}: {{}}\n"
    ).encode()


def trees(name: str = "left-pad", head_range: str = "^1.3.1", head_version: str = "1.3.1", **head_extra: bytes) -> dict:
    base = {
        "pnpm-workspace.yaml": WORKSPACE,
        ".github/renovate.json5": RENOVATE,
        "package.json": manifest(name, "^1.3.0"),
        "pnpm-lock.yaml": lockfile(name, "^1.3.0", "1.3.0"),
    }
    head = {
        **base,
        "package.json": manifest(name, head_range),
        "pnpm-lock.yaml": lockfile(name, head_range, head_version),
    }
    return {WORKFLOW_SHA: base, MERGE_BASE: base, HEAD: {**head, **head_extra}}


class FakeGit:
    def __init__(self, trees: dict, committed: datetime = NOW - timedelta(hours=2)) -> None:
        self.trees, self.committed = trees, committed

    def fetch(self, *shas: str) -> None:
        pass

    def blob(self, ref: str, path: str) -> str | None:
        text = self.trees[ref].get(path)
        return None if text is None else hashlib.sha1(text).hexdigest()

    def show(self, ref: str, path: str) -> bytes | None:
        return self.trees[ref].get(path)

    def changed_files(self, base: str, head: str) -> list[tuple[str, str]]:
        before, after = self.trees[base], self.trees[head]
        changed = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
        return [("M" if path in before and path in after else "A" if path in after else "D", path) for path in changed]

    def commit_time(self, sha: str) -> datetime:
        return self.committed

    def add_worktree(self, directory: Path, sha: str) -> None:
        for path, text in self.trees[sha].items():
            (directory / path).parent.mkdir(parents=True, exist_ok=True)
            (directory / path).write_bytes(text)


class FakeGitHub:
    def __init__(self, author_id: int, head_repository: str = REPOSITORY) -> None:
        self.pr = {
            "number": 123,
            "state": "open",
            "user": {"id": author_id},
            "base": {"ref": "master", "repo": {"full_name": REPOSITORY}},
            "head": {"sha": HEAD, "repo": {"full_name": head_repository}},
        }

    def pull_request(self, head_sha: str, base_branch: str) -> dict:
        return self.pr

    def merge_base(self, base_branch: str, head_sha: str) -> str:
        return MERGE_BASE


class FakePnpm:
    def __init__(self, writes: bytes) -> None:
        self.writes, self.commands = writes, []

    def __call__(self, command: list[str], cwd: Path) -> None:
        self.commands.append((command, cwd))
        if command[0] == "pnpm":
            (cwd / "pnpm-lock.yaml").write_bytes(self.writes)


def registry(name: str) -> dict:
    return {"time": {"1.3.1": "2026-10-01T00:00:00.000Z"}}


def environment(tmp_path: Path, actor: str = str(RENOVATE_BOT_USER_ID)) -> dict[str, str]:
    return {
        "REPOSITORY": REPOSITORY,
        "HEAD_SHA": HEAD,
        "WORKFLOW_SHA": WORKFLOW_SHA,
        "BASE_BRANCH": "master",
        "TRIGGERING_ACTOR_ID": actor,
        "MERGE_BASE_DIR": str(tmp_path / "merge-base"),
    }


def handover(found: prover.Identified) -> dict[str, str]:
    return {"PULL_REQUEST": str(found.pr), "MERGE_BASE": found.merge_base, "ELIGIBLE": json.dumps(found.eligible)}


def prove(
    env: dict[str, str], github: FakeGitHub, git: FakeGit, registry: Callable[[str], dict], pnpm: FakePnpm
) -> prover.Proof:
    return prover.prove({**env, **handover(prover.identify(env, github))}, git, registry, pnpm, NOW)


def test_a_pull_request_by_a_person_attests_nothing(tmp_path: Path) -> None:
    env, github = environment(tmp_path), FakeGitHub(42)
    assert prover.identify(env, github) == prover.Identified(123, MERGE_BASE, False)
    assert prove(env, github, FakeGit({}), registry, FakePnpm(b"")) == prover.Proof([], {})


def test_an_eligible_update_is_attested_after_a_frozen_targeted_replay(tmp_path: Path) -> None:
    pnpm = FakePnpm(lockfile("left-pad", "^1.3.1", "1.3.1", deprecated=True))
    git = FakeGit({**trees(), WORKFLOW_SHA: {**trees()[WORKFLOW_SHA], PROVER: b"the prover"}})
    proof = prove(environment(tmp_path), FakeGitHub(RENOVATE_BOT_USER_ID), git, registry, pnpm)
    assert proof == prover.Proof(
        ["package.json", "pnpm-lock.yaml"],
        {
            ".github/renovate.json5": hashlib.sha1(RENOVATE).hexdigest(),
            ".github/scripts/dependency_proof/__init__.py": None,
            ".github/scripts/dependency_proof/__main__.py": None,
            ".github/scripts/dependency_proof/policy.py": None,
            PROVER: hashlib.sha1(b"the prover").hexdigest(),
            ".github/workflows/dependency-proof-trigger.yml": None,
            ".github/workflows/dependency-proof.yml": None,
            ".npmrc": None,
            ".pnpmfile.cjs": None,
            "pnpm-workspace.yaml": hashlib.sha1(WORKSPACE).hexdigest(),
            "pnpmfile.cjs": None,
        },
    )
    worktree = tmp_path / "merge-base"
    assert pnpm.commands == [
        (["npm", "install", "--global", "--no-audit", "--no-fund", "pnpm@11.28.5"], worktree),
        (
            [
                "pnpm",
                "update",
                "--no-save",
                "left-pad@1.3.1",
                "--lockfile-only",
                "--recursive",
                "--ignore-scripts",
                "--ignore-pnpmfile",
                "--config.minimumReleaseAge=10201",
            ],
            worktree,
        ),
    ]
    assert (worktree / "package.json").read_bytes() == manifest("left-pad", "^1.3.1")
    assert b"minimumReleaseAgeExclude" not in (worktree / "pnpm-workspace.yaml").read_bytes()
    assert b"allowBuilds:\n    esbuild: true\n" in (worktree / "pnpm-workspace.yaml").read_bytes()


@pytest.mark.parametrize(
    ("github", "git", "actor", "replayed", "reason"),
    [
        (
            FakeGitHub(RENOVATE_BOT_USER_ID),
            FakeGit(trees()),
            "19864447",
            None,
            "not triggered by the pull request author",
        ),
        (FakeGitHub(RENOVATE_BOT_USER_ID, "fork/posthog"), FakeGit(trees()), None, None, "not in this repository"),
        (
            FakeGitHub(RENOVATE_BOT_USER_ID),
            FakeGit(trees(), committed=NOW + timedelta(minutes=5)),
            None,
            None,
            "dated in the future",
        ),
        (
            FakeGitHub(RENOVATE_BOT_USER_ID),
            FakeGit(trees(**{"pnpm-workspace.yaml": b"packages: []\n"})),
            None,
            None,
            "neither a manifest nor a lockfile",
        ),
        (
            FakeGitHub(RENOVATE_BOT_USER_ID),
            FakeGit(trees(**{".npmrc": b"audit=false\n"})),
            None,
            None,
            ".npmrc is not a modification",
        ),
        (
            FakeGitHub(RENOVATE_BOT_USER_ID),
            FakeGit({**trees(), WORKFLOW_SHA: {**trees()[WORKFLOW_SHA], ".npmrc": b"audit=false\n"}}),
            None,
            None,
            ".npmrc differs from the default branch",
        ),
        (FakeGitHub(RENOVATE_BOT_USER_ID), FakeGit(trees("esbuild")), None, None, "esbuild is named in allowBuilds"),
        (
            FakeGitHub(RENOVATE_BOT_USER_ID),
            FakeGit(trees("posthog-js")),
            None,
            None,
            "posthog-js is named in minimumReleaseAgeExclude",
        ),
        (
            FakeGitHub(RENOVATE_BOT_USER_ID),
            FakeGit(trees(head_range="^2.0.0", head_version="2.0.0")),
            None,
            None,
            "major change",
        ),
        (
            FakeGitHub(RENOVATE_BOT_USER_ID),
            FakeGit(trees(head_range="npm:left-pad@^1.3.1")),
            None,
            None,
            "not a plain registry",
        ),
        (
            FakeGitHub(RENOVATE_BOT_USER_ID),
            FakeGit(trees()),
            None,
            lockfile("left-pad", "^1.3.1", "1.3.1", integrity="sha512-y"),
            "different pnpm-lock.yaml",
        ),
    ],
)
def test_refusals(
    tmp_path: Path, github: FakeGitHub, git: FakeGit, actor: str | None, replayed: bytes | None, reason: str
) -> None:
    env = environment(tmp_path) if actor is None else environment(tmp_path, actor)
    with pytest.raises(Refused, match=reason):
        prove(env, github, git, registry, FakePnpm(replayed or b""))


@pytest.mark.parametrize(
    ("forged", "reason"),
    [
        ({"PULL_REQUEST": "123; id"}, "not a positive integer"),
        ({"MERGE_BASE": "B" * 40}, "not a commit id"),
        ({"ELIGIBLE": "no"}, "neither true nor false"),
    ],
)
def test_a_malformed_handover_is_refused(tmp_path: Path, forged: dict[str, str], reason: str) -> None:
    env = {**environment(tmp_path), **handover(prover.Identified(123, MERGE_BASE, False)), **forged}
    with pytest.raises(Refused, match=reason):
        prover.prove(env, FakeGit({}), registry, FakePnpm(b""), NOW)


@pytest.mark.parametrize(
    ("published", "reason"),
    [
        ("2026-11-05T00:00:00.000Z", "published 4 day"),
        (None, "no publish time"),
    ],
)
def test_a_young_or_undated_release_is_refused(tmp_path: Path, published: str | None, reason: str) -> None:
    def young_registry(name: str) -> dict:
        return {"time": {} if published is None else {"1.3.1": published}}

    with pytest.raises(Refused, match=reason):
        prove(environment(tmp_path), FakeGitHub(RENOVATE_BOT_USER_ID), FakeGit(trees()), young_registry, FakePnpm(b""))


def test_comparable_ignores_only_a_deprecation_under_a_package() -> None:
    plain, deprecated = (
        lockfile("left-pad", "^1.3.1", "1.3.1"),
        lockfile("left-pad", "^1.3.1", "1.3.1", deprecated=True),
    )
    assert prover.comparable(plain) == prover.comparable(deprecated)
    assert prover.comparable(plain) != prover.comparable(lockfile("left-pad", "^1.3.1", "1.3.2"))
    elsewhere = plain.replace(b"        version: 1.3.1\n", b"        version: 1.3.1\n        deprecated: x\n")
    assert prover.comparable(plain) != prover.comparable(elsewhere)


def test_comparable_reads_scalars_as_text_and_refuses_a_repeated_key() -> None:
    assert prover.comparable(b"a: 1.10\n") != prover.comparable(b"a: 1.1\n")
    assert prover.comparable(b"a: yes\n") == {"a": "yes"}
    with pytest.raises(Refused, match="repeats a key"):
        prover.comparable(b"a: 1\na: 2\n")
    with pytest.raises(Refused, match="alias"):
        prover.comparable(b"a: &x 1\nb: *x\n")


def test_frozen_workspace_settings_drop_the_repository_exclusions() -> None:
    frozen = prover.frozen_workspace_settings((REPO_ROOT / "pnpm-workspace.yaml").read_bytes())
    assert b"minimumReleaseAgeExclude" not in frozen
    assert b"posthog-js-lite" not in frozen
    assert b"minimumReleaseAge: 10080\n" in frozen
    assert b"allowBuilds:\n" in frozen


class StubGitHub(prover.GitHub):
    def __init__(self, pulls: list[dict]) -> None:
        super().__init__(REPOSITORY, "token")
        self.pulls = pulls

    def get(self, path: str) -> list[dict]:
        return self.pulls


def pull(state: str = "open", base: str = "master", head: str = HEAD, base_repository: str = REPOSITORY) -> dict:
    return {"state": state, "base": {"ref": base, "repo": {"full_name": base_repository}}, "head": {"sha": head}}


@pytest.mark.parametrize(
    ("pulls", "reason"),
    [
        ([pull()], None),
        ([pull(), pull(state="closed"), pull(base="feature"), pull(base_repository="fork/posthog")], None),
        ([], "0 open pull requests"),
        ([pull(), pull()], "2 open pull requests"),
        ([pull(head="d" * 40)], "head has moved"),
    ],
)
def test_pull_request_lookup(pulls: list[dict], reason: str | None) -> None:
    if reason is None:
        assert StubGitHub(pulls).pull_request(HEAD, "master") == pull()
    else:
        with pytest.raises(Refused, match=reason):
            StubGitHub(pulls).pull_request(HEAD, "master")


def test_git_reads_trees_without_running_hooks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *args], cwd=repo, check=True, capture_output=True, env=env
        ).stdout.decode()

    git("init", "-q", "-b", "master")
    (repo / "package.json").write_bytes(b"{}")
    (repo / "pnpm-lock.yaml").write_bytes(b"lockfileVersion: '9.0'\n")
    git("add", ".")
    git("commit", "-q", "-m", "base")
    base = git("rev-parse", "HEAD").strip()
    (repo / "package.json").write_bytes(b'{"a": 1}')
    (repo / "renovate.json5").symlink_to("package.json")
    git("add", ".")
    git("commit", "-q", "-m", "head")
    head = git("rev-parse", "HEAD").strip()
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "post-checkout").write_text("#!/bin/sh\ntouch hook-ran\n")
    (hooks / "post-checkout").chmod(stat.S_IRWXU)
    git("config", "core.hooksPath", str(hooks))

    reader = prover.Git(repo)
    assert reader.changed_files(base, head) == [("M", "package.json"), ("A", "renovate.json5")]
    assert reader.show(head, "package.json") == b'{"a": 1}'
    assert reader.blob(head, "missing.json") is None
    with pytest.raises(Refused, match="not a regular file"):
        reader.blob(head, "renovate.json5")
    assert reader.commit_time(head).tzinfo is UTC
    reader.add_worktree(tmp_path / "worktree", base)
    assert (tmp_path / "worktree" / "package.json").read_bytes() == b"{}"
    assert not (tmp_path / "worktree" / "hook-ran").exists()
