import io
import os
import sys
import json
import stat
import hashlib
import subprocess
import http.client
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from dependency_proof import prove as prover
from dependency_proof.policy import RENOVATE_BOT_USER_ID, Refused

REPOSITORY = "PostHog/posthog"
HEAD, MERGE_BASE, WORKFLOW_SHA = "a" * 40, "b" * 40, "c" * 40
NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)
WORKSPACE = b"packages:\n    - '.'\nminimumReleaseAge: 10080\nminimumReleaseAgeExclude:\n    - posthog-js\n    - '@posthog/*'\n    - left-pad@1.3.0\nallowBuilds:\n    esbuild: true\n"
PROVER = ".github/scripts/dependency_proof/prove.py"
REPLAY_FLAGS = ["--lockfile-only", "--recursive", "--ignore-scripts", "--ignore-pnpmfile"]


def _fake_blob_sha(text: bytes) -> str:
    return hashlib.sha256(text).hexdigest()[:40]


def manifest(name: str, version_range: str) -> bytes:
    return json.dumps(
        {"name": "root", "packageManager": "pnpm@11.28.5", "dependencies": {name: version_range}}
    ).encode()


def lockfile(
    name: str,
    specifier: str,
    version: str,
    integrity: str = "sha512-x",
    deprecated: bool = False,
    catalog: str | None = None,
) -> bytes:
    deprecation = "    deprecated: |-\n      use something else,\n      see the notes\n" if deprecated else ""
    snapshot = (
        f"catalogs:\n  default:\n    {name}:\n      specifier: {catalog}\n      version: {version}\n\n"
        if catalog
        else ""
    )
    return (
        f"lockfileVersion: '9.0'\n\n{snapshot}importers:\n\n  .:\n    dependencies:\n      {name}:\n        specifier: '{specifier}'\n"
        f"        version: {version}\n\npackages:\n\n  {name}@{version}:\n    resolution: {{integrity: {integrity}}}\n"
        f"{deprecation}\nsnapshots:\n\n  {name}@{version}: {{}}\n"
    ).encode()


def trees(name: str = "left-pad", head_range: str = "^1.3.1", head_version: str = "1.3.1", **head_extra: bytes) -> dict:
    base = {
        "pnpm-workspace.yaml": WORKSPACE,
        "package.json": manifest(name, "^1.3.0"),
        "pnpm-lock.yaml": lockfile(name, "^1.3.0", "1.3.0"),
    }
    head = {
        **base,
        "package.json": manifest(name, head_range),
        "pnpm-lock.yaml": lockfile(name, head_range, head_version),
    }
    return {WORKFLOW_SHA: base, MERGE_BASE: base, HEAD: {**head, **head_extra}}


def catalog_trees(head_catalog: str = "^1.3.1", head_version: str = "1.3.1") -> dict:
    def workspace(catalog: str) -> bytes:
        return WORKSPACE + f"catalog:\n    left-pad: {catalog}\n".encode()

    base = {
        "pnpm-workspace.yaml": workspace("^1.3.0"),
        "package.json": manifest("left-pad", "catalog:"),
        "pnpm-lock.yaml": lockfile("left-pad", "catalog:", "1.3.0", catalog="^1.3.0"),
    }
    head = {
        **base,
        "pnpm-workspace.yaml": workspace(head_catalog),
        "pnpm-lock.yaml": lockfile("left-pad", "catalog:", head_version, catalog=head_catalog),
    }
    return {WORKFLOW_SHA: base, MERGE_BASE: base, HEAD: head}


def every_tree(**files: bytes | None) -> dict:
    return {
        sha: {path: text for path, text in {**tree, **files}.items() if text is not None}
        for sha, tree in trees().items()
    }


class FakeGit:
    def __init__(self, trees: dict, committed: datetime = NOW - timedelta(hours=2)) -> None:
        self.trees, self.committed = trees, committed

    def fetch(self, *shas: str) -> None:
        pass

    def blob(self, ref: str, path: str) -> str | None:
        text = self.trees[ref].get(path)
        return None if text is None else _fake_blob_sha(text)

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


def pull(
    author: int = RENOVATE_BOT_USER_ID,
    state: str = "open",
    base: str = "master",
    head: str = HEAD,
    head_repository: str = REPOSITORY,
) -> dict:
    return {
        "number": 123,
        "state": state,
        "user": {"id": author},
        "base": {"ref": base},
        "head": {"sha": head, "ref": "renovate/left-pad", "repo": {"full_name": head_repository}},
    }


class FakeGitHub(prover.GitHub):
    def __init__(self, *pulls: dict, pusher: int = RENOVATE_BOT_USER_ID) -> None:
        super().__init__(REPOSITORY, "token")
        self.pulls, self.pusher = list(pulls), pusher

    def get(self, path: str) -> Any:
        if path.startswith("commits/"):
            return self.pulls
        if path.startswith("activity?ref=refs%2Fheads%2Frenovate%2Fleft-pad&"):
            return [{"after": "d" * 40, "actor": {"id": 42}}, {"after": HEAD, "actor": {"id": self.pusher}}]
        return {"merge_base_commit": {"sha": MERGE_BASE}}


class FakePnpm:
    def __init__(self, writes: bytes) -> None:
        self.writes, self.commands = writes, []

    def __call__(self, command: list[str], cwd: Path) -> None:
        self.commands.append((command, cwd))
        if command[0] == "pnpm":
            (cwd / "pnpm-lock.yaml").write_bytes(self.writes)


def registry(name: str) -> dict:
    return {"time": {"1.3.1": "2026-10-01T00:00:00.000Z"}}


def environment(tmp_path: Path) -> dict[str, str]:
    return {
        "REPOSITORY": REPOSITORY,
        "HEAD_SHA": HEAD,
        "WORKFLOW_SHA": WORKFLOW_SHA,
        "BASE_BRANCH": "master",
        "MERGE_BASE_DIR": str(tmp_path / "merge-base"),
    }


def handover(found: prover.Identified) -> dict[str, str]:
    return {"PULL_REQUEST": str(found.pr), "MERGE_BASE": found.merge_base}


def prove(
    env: dict[str, str], github: FakeGitHub, git: FakeGit, registry: Callable[[str], dict], pnpm: FakePnpm
) -> prover.Proof:
    found = prover.identify(env, github)
    assert found is not None
    return prover.prove({**env, **handover(found)}, git, registry, pnpm, NOW)


INSTALL = ["pnpm", "install", *REPLAY_FLAGS, "--no-frozen-lockfile"]


@pytest.mark.parametrize(
    ("update", "replayed", "files", "replay"),
    [
        (
            trees(),
            lockfile("left-pad", "^1.3.1", "1.3.1", deprecated=True),
            ["package.json", "pnpm-lock.yaml"],
            INSTALL,
        ),
        (
            trees(head_range="^1.3.0"),
            lockfile("left-pad", "^1.3.0", "1.3.1"),
            ["pnpm-lock.yaml"],
            ["pnpm", "update", "--no-save", "left-pad@1.3.1", *REPLAY_FLAGS],
        ),
        (
            catalog_trees(),
            lockfile("left-pad", "catalog:", "1.3.1", catalog="^1.3.1"),
            ["pnpm-lock.yaml", "pnpm-workspace.yaml"],
            INSTALL,
        ),
    ],
)
def test_an_eligible_update_is_attested_after_a_frozen_replay_of_renovates_command(
    tmp_path: Path, update: dict, replayed: bytes, files: list[str], replay: list[str]
) -> None:
    pnpm = FakePnpm(replayed)
    git = FakeGit({**update, WORKFLOW_SHA: {**update[WORKFLOW_SHA], PROVER: b"the prover"}})
    proof = prove(environment(tmp_path), FakeGitHub(pull()), git, registry, pnpm)
    assert proof == prover.Proof(
        files,
        {
            ".github/actions/setup-uv/action.yml": None,
            ".github/scripts/dependency_proof/__init__.py": None,
            ".github/scripts/dependency_proof/__main__.py": None,
            ".github/scripts/dependency_proof/policy.py": None,
            PROVER: _fake_blob_sha(b"the prover"),
            ".github/workflows/dependency-proof-trigger.yml": None,
            ".github/workflows/dependency-proof.yml": None,
            ".npmrc": None,
            ".nvmrc": None,
            ".pnpmfile.cjs": None,
            "pnpm-workspace.yaml": _fake_blob_sha(update[WORKFLOW_SHA]["pnpm-workspace.yaml"]),
            "pnpmfile.cjs": None,
        },
    )
    worktree = tmp_path / "merge-base"
    assert pnpm.commands == [
        (["npm", "install", "--global", "--no-audit", "--no-fund", "pnpm@11.28.5"], worktree),
        ([*replay, "--config.minimumReleaseAge=10201"], worktree),
    ]
    assert (worktree / "package.json").read_bytes() == update[HEAD]["package.json"]
    assert (worktree / "pnpm-workspace.yaml").read_bytes() == update[HEAD]["pnpm-workspace.yaml"]


def stray(path: str, base: bytes, head: bytes) -> dict:
    return {sha: {**tree, path: head if sha == HEAD else base} for sha, tree in trees().items()}


@pytest.mark.parametrize(
    ("github", "update", "replayed", "reason"),
    [
        (FakeGitHub(pull(), pusher=42), trees(), None, "not pushed by the pull request author"),
        (FakeGitHub(pull(head_repository="fork/posthog")), trees(), None, "not in this repository"),
        (
            None,
            trees(**{"pnpm-workspace.yaml": WORKSPACE.replace(b"'.'", b'"."')}),
            None,
            "differs from the default branch by more than a catalog version",
        ),
        (None, trees(**{".npmrc": b"audit=false\n"}), None, ".npmrc is not a modification"),
        (
            None,
            {**trees(), WORKFLOW_SHA: {**trees()[WORKFLOW_SHA], ".npmrc": b"audit=false\n"}},
            None,
            ".npmrc differs from the default branch",
        ),
        (None, trees("esbuild"), None, "esbuild is named in allowBuilds"),
        (None, trees("posthog-js"), None, "posthog-js is named in minimumReleaseAgeExclude"),
        (
            None,
            {**trees(), WORKFLOW_SHA: {**trees()[WORKFLOW_SHA], "package.json": b'{"pnpm": {"overrides": {}}}'}},
            None,
            "package.json pnpm settings differ from the default branch",
        ),
        (None, trees(head_range="^2.0.0", head_version="2.0.0"), None, "major change"),
        (None, trees(), lockfile("left-pad", "^1.3.1", "1.3.1", integrity="sha512-y"), "different pnpm-lock.yaml"),
        (None, every_tree(**{"pnpm-workspace.yaml": None}), None, "pnpm-workspace.yaml is missing"),
        (
            None,
            stray("tools/package.json", manifest("left-pad", "^1.3.0"), manifest("left-pad", "^1.3.1")),
            None,
            "tools/package.json is not a project of pnpm-lock.yaml",
        ),
        (
            None,
            stray("tools/pnpm-workspace.yaml", b"packages: []\n", b"packages: ['*']\n"),
            None,
            "tools/pnpm-workspace.yaml is not beside a lockfile",
        ),
        (None, catalog_trees(head_catalog="~1.3.1"), None, "changes the range operator"),
        (None, catalog_trees(head_version="1.3.0"), None, "left-pad is named in minimumReleaseAgeExclude"),
        (None, trees("ms", head_version="1.3.0"), None, "changes no direct dependency version"),
    ],
)
def test_refusals(tmp_path: Path, github: FakeGitHub | None, update: dict, replayed: bytes | None, reason: str) -> None:
    with pytest.raises(Refused, match=reason):
        prove(environment(tmp_path), github or FakeGitHub(pull()), FakeGit(update), registry, FakePnpm(replayed or b""))


def test_a_head_commit_dated_in_the_future_is_refused(tmp_path: Path) -> None:
    git = FakeGit(trees(), committed=NOW + timedelta(minutes=5))
    with pytest.raises(Refused, match="dated in the future"):
        prove(environment(tmp_path), FakeGitHub(pull()), git, registry, FakePnpm(b""))


@pytest.mark.parametrize(
    ("forged", "reason"),
    [
        ({"PULL_REQUEST": "123; id"}, "not a positive integer"),
        ({"MERGE_BASE": "B" * 40}, "not a commit id"),
    ],
)
def test_a_malformed_handover_is_refused(tmp_path: Path, forged: dict[str, str], reason: str) -> None:
    env = {**environment(tmp_path), **handover(prover.Identified(123, MERGE_BASE)), **forged}
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
        prove(environment(tmp_path), FakeGitHub(pull()), FakeGit(trees()), young_registry, FakePnpm(b""))


def test_comparable_ignores_only_a_deprecation_under_a_package() -> None:
    plain, deprecated = (
        lockfile("left-pad", "^1.3.1", "1.3.1"),
        lockfile("left-pad", "^1.3.1", "1.3.1", deprecated=True),
    )
    assert prover.comparable(plain) == prover.comparable(deprecated)
    assert prover.comparable(plain) != prover.comparable(lockfile("left-pad", "^1.3.1", "1.3.2"))
    elsewhere = plain.replace(b"        version: 1.3.1\n", b"        version: 1.3.1\n        deprecated: x\n")
    assert prover.comparable(plain) != prover.comparable(elsewhere)


@pytest.mark.parametrize(
    ("one", "other", "same"),
    [
        (b"a: 1.10\n", b"a: 1.1\n", False),
        (b"a: true\n", b'a: "true"\n', False),
        (b"a: 1e3\n", b"a: '1e3'\n", False),
        (b"a: 1.5e3\n", b"a: '1.5e3'\n", False),
        (b"a: .5e3\n", b"a: '.5e3'\n", False),
        (b"a: 0o17\n", b"a: '0o17'\n", False),
        (b"a: ~\n", b"a: 'null'\n", False),
        (b"a: ~\n", b"a: null\n", True),
        (b"a: '1.0'\n", b'a: "1.0"\n', True),
        (b"a: left-pad\n", b"a: 'left-pad'\n", True),
    ],
)
def test_comparable_keeps_scalars_that_pnpm_reads_differently_apart(one: bytes, other: bytes, same: bool) -> None:
    assert (prover.comparable(one) == prover.comparable(other)) is same


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        (b"a: 1\na: 2\n", "repeats a key"),
        (b"? [a]\n: 1\n", "a key that is not a scalar"),
        (b'a: [deprecated, "b \n  c"]\n', "spreads a scalar over lines"),
        (b"packages:\n  a@1.0.0:\n    engines: |\n      node\n", "spreads a scalar over lines"),
        (b"snapshots:\n  a@1.0.0:\n    deprecated: |\n      b\n", "spreads a scalar over lines"),
        (b"packages:\n  a@1.0.0:\n    deprecated:\n      b: |\n        c\n", "spreads a scalar over lines"),
        (b"packages:\n  a@1.0.0:\n    deprecated:\n      ? |\n        b\n      : c\n", "spreads a scalar over lines"),
        (b"- packages:\n    a@1.0.0:\n      deprecated: |\n        b\n", "spreads a scalar over lines"),
        (b"a: [1\n", "does not parse"),
        (b"a: &x 1\nb: *x\n", "an alias or an explicit tag"),
        (b"hasBin: !!int true\n", "an alias or an explicit tag"),
        (b"a: !!map {}\n", "an alias or an explicit tag"),
        (b"---\na: 1\n", "a document marker"),
        ("a: 1\N{LINE SEPARATOR}b: 2\n".encode(), "a line separator"),
        ("a: 1\x85b: 2\n".encode(), "a line separator"),
        ("a: 1\n".encode("utf-16"), "not UTF-8"),
        ("a: 1\n".encode("utf-8-sig"), "a byte order mark"),
    ],
)
def test_comparable_refuses_yaml_that_pnpm_never_writes(text: bytes, reason: str) -> None:
    with pytest.raises(Refused, match=reason):
        prover.comparable(text)


@pytest.mark.parametrize("error", [ConnectionResetError("reset"), http.client.IncompleteRead(b"{")])
def test_fetch_retries_a_transport_failure(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    class Response(io.BytesIO):
        def read(self, *_: object) -> bytes:
            if failures:
                raise failures.pop()
            return b"{}"

    failures = [error]
    monkeypatch.setattr(prover.OPENER, "open", lambda request, timeout: Response())
    monkeypatch.setattr(prover.time, "sleep", lambda seconds: None)

    assert prover.fetch(urllib.request.Request("https://registry.npmjs.org/left-pad")) == b"{}"


@pytest.mark.parametrize(
    ("pulls", "expected"),
    [
        ([pull()], prover.Identified(123, MERGE_BASE)),
        (
            [pull(), pull(state="closed"), pull(base="feature"), pull(head="d" * 40), pull(author=42)],
            prover.Identified(123, MERGE_BASE),
        ),
        ([pull(), pull(author=42, head_repository="fork/posthog")], prover.Identified(123, MERGE_BASE)),
        ([], None),
        ([pull(), pull()], "2 pull requests by an allowed author"),
        ([pull()] * 100, "more pull requests contain this commit"),
    ],
)
def test_identify(tmp_path: Path, pulls: list[dict], expected: prover.Identified | str | None) -> None:
    if isinstance(expected, str):
        with pytest.raises(Refused, match=expected):
            prover.identify(environment(tmp_path), FakeGitHub(*pulls))
    else:
        assert prover.identify(environment(tmp_path), FakeGitHub(*pulls)) == expected


def test_a_refusal_is_logged_while_the_runner_reads_no_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(*_: object) -> None:
        raise Refused("##[set-output name=eligible]true")

    monkeypatch.setattr(prover, "identify", refuse)
    monkeypatch.setattr(prover.sys, "argv", ["prove.py", "identify"])
    monkeypatch.setenv("REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary"))

    assert prover.main() == 0
    stopped, refusal, resumed = capsys.readouterr().out.splitlines()
    assert refusal == "Refused: ##[set-output name=eligible]true"
    assert resumed == f"::{stopped.removeprefix('::stop-commands::')}::"
    assert (tmp_path / "output").read_text() == "pr=0\nmerge_base=\neligible=false\nrefused=true\n"


def test_a_replayed_command_gets_no_runner_file_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    prover.run_command([sys.executable, "-c", "import os, sys; sys.exit('GITHUB_OUTPUT' in os.environ)"], tmp_path)


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
    git("sparse-checkout", "set", "--no-cone", "/package.json")

    reader = prover.Git(repo)
    assert reader.changed_files(base, head) == [("M", "package.json"), ("A", "renovate.json5")]
    assert reader.show(head, "package.json") == b'{"a": 1}'
    assert reader.blob(head, "missing.json") is None
    with pytest.raises(Refused, match="not a regular file"):
        reader.blob(head, "renovate.json5")
    assert reader.commit_time(head).tzinfo is UTC
    reader.add_worktree(tmp_path / "worktree", base)
    assert (tmp_path / "worktree" / "package.json").read_bytes() == b"{}"
    assert (tmp_path / "worktree" / "pnpm-lock.yaml").exists()
    assert not (tmp_path / "worktree" / "hook-ran").exists()
