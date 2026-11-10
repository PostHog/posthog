"""Prove one pull request's dependency update from the default branch and the merge base."""

from __future__ import annotations

import os
import re
import sys
import json
import time
import secrets
import subprocess
import http.client
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from dependency_proof import policy
from dependency_proof.policy import LOCKFILE, MANIFEST, WORKSPACE_FILE, Refused, join

YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
REGISTRY = "https://registry.npmjs.org/"
RELEASE_AGE_LOOKUPS = 50
# Matches the whole block, because the frozen registry view below must not exempt its entries.
RELEASE_AGE_EXCLUSIONS = re.compile(rb"^minimumReleaseAgeExclude:\n(?:(?:[ \t]+.*|)\n)*", re.MULTILINE)
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
PULL_REQUEST_NUMBER = re.compile(r"[1-9][0-9]*")
PULL_REQUEST_PAGE = 100
PROVER_FILES = (
    ".github/scripts/dependency_proof/__init__.py",
    ".github/scripts/dependency_proof/__main__.py",
    ".github/scripts/dependency_proof/policy.py",
    ".github/scripts/dependency_proof/prove.py",
    ".github/workflows/dependency-proof-trigger.yml",
    ".github/workflows/dependency-proof.yml",
)
Runner = Callable[[list[str], Path], None]


@dataclass(frozen=True)
class Unquoted:
    """A scalar that YAML reads as something other than a string, kept as the text in the file."""

    text: str

    def __str__(self) -> str:
        return self.text


class StrictLoader(YAML_LOADER):  # type: ignore[misc,valid-type]
    """Reads YAML without converting a scalar, and refuses repeated keys and aliases.

    The replay and the head lockfile are compared as the structures this loader builds, so it must
    not read two different texts as one structure. Type coercion would, because `1.10` and `1.1` are
    one float. Reading every scalar as a string would too, because pnpm reads `true` as a boolean and
    `"true"` as a string. So a string stays a `str`, a null stays `None`, and any other scalar becomes
    an `Unquoted` that holds its text. A repeated key is refused, because this parser keeps the last
    value and pnpm's may not.
    """

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        if len(set(keys)) != len(keys):
            raise Refused("a lockfile repeats a key")
        return super().construct_mapping(node, deep=deep)


for _tag in ("bool", "int", "float", "timestamp"):
    StrictLoader.add_constructor(f"tag:yaml.org,2002:{_tag}", lambda _loader, node: Unquoted(node.value))
# PyYAML resolves YAML 1.1. pnpm reads YAML 1.2, where a number needs neither a dot nor a sign on
# its exponent, and where `0o` starts an octal. This pattern also takes the `_` that js-yaml allows.
StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(r"^[-+]?(?:(?:[0-9][0-9_]*(?:\.[0-9_]*)?|\.[0-9_]+)(?:[eE][-+]?[0-9]+)?|0o[0-7_]+)$"),
    list("-+.0123456789"),
)


@dataclass(frozen=True)
class Identified:
    pr: int
    merge_base: str


@dataclass(frozen=True)
class Proof:
    files: list[str]
    blobs: dict[str, str | None]


class Git:
    """Reads trees from the object database, so a sparse checkout is enough. Hooks never run."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def run(self, *args: str) -> bytes:
        command = ["git", "-c", "core.hooksPath=/dev/null", *args]
        return subprocess.run(command, cwd=self.repo, check=True, capture_output=True).stdout

    def fetch(self, *shas: str) -> None:
        self.run("fetch", "--no-tags", "--depth=1", "origin", *shas)

    def blob(self, ref: str, path: str) -> str | None:
        """The blob id at ref:path, or None when absent. A symlink would judge its target, so it is refused."""
        line = self.run("ls-tree", ref, "--", path).decode()
        if not line:
            return None
        mode, kind, oid = line.split("\t", 1)[0].split()
        if kind != "blob" or mode == "120000":
            raise Refused(f"{path} is not a regular file")
        return oid

    def show(self, ref: str, path: str) -> bytes | None:
        oid = self.blob(ref, path)
        return None if oid is None else self.run("cat-file", "blob", oid)

    def changed_files(self, base: str, head: str) -> list[tuple[str, str]]:
        fields = self.run("diff", "--name-status", "--no-renames", "-z", base, head).decode().split("\0")
        return list(zip(fields[0::2], fields[1::2]))

    def commit_time(self, sha: str) -> datetime:
        return datetime.fromtimestamp(int(self.run("log", "-1", "--format=%ct", sha)), UTC)

    def add_worktree(self, directory: Path, sha: str) -> None:
        self.run("worktree", "add", "--detach", str(directory), sha)
        # A new worktree copies the sparse patterns of the checkout it comes from, and pnpm needs the whole tree.
        self.run("-C", str(directory), "sparse-checkout", "disable")


class GitHub:
    def __init__(self, repository: str, token: str) -> None:
        self.repository, self.token = repository, token

    def get(self, path: str) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        return json.loads(
            fetch(urllib.request.Request(f"https://api.github.com/repos/{self.repository}/{path}", headers=headers))
        )

    def pull_requests(self, head_sha: str, base_branch: str) -> list[dict[str, Any]]:
        """The open pull requests into the base branch whose head is this commit."""
        listed = self.get(f"commits/{head_sha}/pulls?per_page={PULL_REQUEST_PAGE}")
        if len(listed) >= PULL_REQUEST_PAGE:
            raise Refused("more pull requests contain this commit than this proof reads")
        return [
            pr
            for pr in listed
            if pr["state"] == "open" and pr["base"]["ref"] == base_branch and pr["head"]["sha"] == head_sha
        ]

    def merge_base(self, base_branch: str, head_sha: str) -> str:
        return self.get(f"compare/{base_branch}...{head_sha}?per_page=1")["merge_base_commit"]["sha"]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Fails a redirect, because urllib would send the Authorization header on to the new host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def fetch(request: urllib.request.Request, attempts: int = 3) -> bytes:
    """A GET with retries on transport errors and 5xx. Anything else fails the proof."""
    if request.type != "https":
        raise ValueError(f"refusing a non-https URL: {request.full_url}")
    for attempt in range(attempts):
        try:
            # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected -- the scheme is checked above, and both callers build the URL from a constant https origin
            with OPENER.open(request, timeout=60) as response:
                return response.read()
        # A body cut short raises IncompleteRead, which is an HTTPException and not an OSError.
        except (OSError, http.client.HTTPException) as error:
            if attempt == attempts - 1 or (isinstance(error, urllib.error.HTTPError) and error.code < 500):
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def registry_metadata(name: str) -> Mapping[str, Any]:
    request = urllib.request.Request(
        REGISTRY + urllib.parse.quote(name, safe="@"), headers={"Accept": "application/json"}
    )
    return json.loads(fetch(request))


def run_command(command: list[str], cwd: Path) -> None:
    # The `GITHUB_*` variables name the files the runner reads step outputs and environment changes
    # from, and a package manager has no use for them.
    env = {name: value for name, value in os.environ.items() if not name.startswith("GITHUB_")}
    subprocess.run(command, cwd=cwd, check=True, env=env)


def replay_command(updates: list[str], recursive: bool, release_age_minutes: int) -> list[str]:
    """Renovate's targeted pnpm update, replayed against the registry as Renovate saw it at the head commit.

    pnpm counts `minimumReleaseAge` back from now, so the head's own view is the policy's release age
    plus the time since the head commit. That hides everything published since the head commit,
    which keeps caret ranges and `latest` dist-tags from resolving to newer versions, and it holds
    every transitive dependency the update pulls in to the same age as Renovate's run did.
    """
    return [
        "pnpm",
        "update",
        "--no-save",
        *updates,
        "--lockfile-only",
        *(["--recursive"] if recursive else []),
        "--ignore-scripts",
        "--ignore-pnpmfile",
        f"--config.minimumReleaseAge={release_age_minutes}",
    ]


def frozen_workspace_settings(text: bytes) -> bytes:
    """The workspace settings without `minimumReleaseAgeExclude`, so the frozen age applies to every package."""
    frozen = RELEASE_AGE_EXCLUSIONS.sub(b"", text)
    if "minimumReleaseAgeExclude" in load_yaml(frozen):
        raise Refused(f"{WORKSPACE_FILE} writes minimumReleaseAgeExclude in a form this proof does not read")
    return frozen


def comparable(lockfile: bytes) -> dict[str, Any]:
    """The lockfile as pnpm reads it, without the one field the registry sets after resolution.

    npm's `deprecated` metadata follows the registry, not the resolution, so a replay cannot reproduce
    it. Only a string under a `packages` entry is dropped, where pnpm writes it. Anywhere else it has
    to match the replay like every other key.
    """
    loaded = load_yaml(lockfile)
    for entry in (loaded.get("packages") or {}).values():
        if isinstance(entry, dict) and isinstance(entry.get("deprecated"), str):
            del entry["deprecated"]
    return loaded


def replay_lockfile(
    worktree: Path, directory: str, head_manifests: Mapping[str, bytes], command: list[str], run: Runner
) -> bytes:
    """The lockfile pnpm writes in the merge-base tree once the head manifests are in place."""
    for path, text in head_manifests.items():
        (worktree / path).write_bytes(text)
    workspace = worktree / join(directory, WORKSPACE_FILE)
    workspace.write_bytes(frozen_workspace_settings(workspace.read_bytes()))
    run(command, worktree / directory)
    return (worktree / join(directory, LOCKFILE)).read_bytes()


def identify(env: Mapping[str, str], github: GitHub) -> Identified | None:
    """The pull request to prove at the head named in ``env``, or None when no author there may have a proof.

    Pull requests by other authors are ignored, so a second pull request opened at the same head, from a
    fork for example, cannot void the proof.
    """
    head, base_branch = env["HEAD_SHA"], env["BASE_BRANCH"]
    candidates = [pr for pr in github.pull_requests(head, base_branch) if pr["user"]["id"] in policy.ALLOWED_AUTHOR_IDS]
    if not candidates:
        return None
    if len(candidates) > 1:
        raise Refused(f"{len(candidates)} pull requests by an allowed author have this head")
    pr = candidates[0]
    if (pr["head"].get("repo") or {}).get("full_name") != env["REPOSITORY"]:
        raise Refused("the head branch is not in this repository")
    if env["TRIGGERING_ACTOR_ID"] != str(pr["user"]["id"]):
        raise Refused("the run was not triggered by the pull request author")
    return Identified(pr["number"], github.merge_base(base_branch, head))


def handed_over(env: Mapping[str, str]) -> Identified | None:
    """What the identification job handed over, refused unless every value has its exact shape."""
    pr, merge_base, eligible = env["PULL_REQUEST"], env["MERGE_BASE"], env["ELIGIBLE"]
    if eligible not in ("true", "false"):
        raise Refused("the eligibility is neither true nor false")
    if eligible == "false":
        return None
    if not PULL_REQUEST_NUMBER.fullmatch(pr):
        raise Refused("the pull request number is not a positive integer")
    if not COMMIT_SHA.fullmatch(merge_base):
        raise Refused("the merge base is not a commit id")
    return Identified(int(pr), merge_base)


def prove(
    env: Mapping[str, str],
    git: Git,
    registry: Callable[[str], Mapping[str, Any]],
    run: Runner,
    now: datetime,
) -> Proof:
    """The proof for the pull request named in ``env``, or a Refused saying what stops it."""
    head, workflow_sha = env["HEAD_SHA"], env["WORKFLOW_SHA"]
    pull_request = handed_over(env)
    if pull_request is None:
        return Proof([], {})
    merge_base = pull_request.merge_base

    git.fetch(merge_base, head)
    files = policy.eligible_paths(git.changed_files(merge_base, head))
    renovate = policy.json5_loads(
        require(git.show(workflow_sha, ".github/renovate.json5"), ".github/renovate.json5").decode()
    )
    groups = lockfile_groups(files, git, merge_base)
    worktree = Path(env["MERGE_BASE_DIR"])
    git.add_worktree(worktree, merge_base)
    committed = git.commit_time(head)
    if committed > now:
        raise Refused("the head commit is dated in the future")
    started = time.monotonic()

    def release_age_minutes() -> int:
        # pnpm reads its own clock when it runs, which is later than `now` by the time spent since.
        since_head = (now - committed).total_seconds() + time.monotonic() - started
        return int(since_head // 60) + 1 + int(policy.MINIMUM_RELEASE_AGE.total_seconds() // 60)

    pinned = set(PROVER_FILES)
    for directory, manifests in groups.items():
        pinned |= prove_group(
            git,
            registry,
            run,
            now,
            worktree,
            workflow_sha,
            merge_base,
            head,
            renovate,
            directory,
            manifests,
            release_age_minutes,
        )
    return Proof(files, {path: git.blob(workflow_sha, path) for path in sorted(pinned)})


def lockfile_groups(files: list[str], git: Git, merge_base: str) -> dict[str, list[str]]:
    """Changed manifests keyed by the lockfile directory whose workspace they belong to."""
    groups: dict[str, list[str]] = {}
    for path in files:
        directory = policy.lockfile_dir(path, lambda candidate: git.blob(merge_base, candidate) is not None)
        if path.rpartition("/")[2] == LOCKFILE:
            groups.setdefault(directory, [])
            continue
        workspace = load_workspace(git, merge_base, directory)
        relative = path.rpartition("/")[0][len(directory) :].lstrip("/")
        if not policy.is_workspace_member(relative, workspace.get("packages") or []):
            raise Refused(f"{path} is outside the workspace of {join(directory, LOCKFILE)}")
        groups.setdefault(directory, []).append(path)
    for directory in groups:
        if join(directory, LOCKFILE) not in files:
            raise Refused(f"{join(directory, LOCKFILE)} did not change")
    return groups


def prove_group(
    git: Git,
    registry: Callable[[str], Mapping[str, Any]],
    run: Runner,
    now: datetime,
    worktree: Path,
    workflow_sha: str,
    merge_base: str,
    head: str,
    renovate: Mapping[str, Any],
    directory: str,
    manifests: list[str],
    release_age_minutes: Callable[[], int],
) -> set[str]:
    """Proves one lockfile directory and returns the settings paths its proof read."""
    lockfile, root_manifest = join(directory, LOCKFILE), join(directory, MANIFEST)
    workspace = load_workspace(git, workflow_sha, directory)
    settings = policy.settings_paths(directory, workspace)
    for path in settings:
        if git.blob(head, path) != git.blob(workflow_sha, path):
            raise Refused(f"{path} differs from the default branch")
    default_manifest = policy.load_manifest(require(git.show(workflow_sha, root_manifest), root_manifest))
    if policy.load_manifest(require(git.show(head, root_manifest), root_manifest)).get("pnpm") != default_manifest.get(
        "pnpm"
    ):
        raise Refused(f"{root_manifest} pnpm settings differ from the default branch")
    only_built = workspace.get("onlyBuiltDependenciesFile")
    only_built_text = (
        require(git.show(workflow_sha, join(directory, str(only_built))), str(only_built)) if only_built else None
    )
    blocked = policy.blocked_patterns(
        workspace, default_manifest, renovate, None if only_built_text is None else only_built_text.decode()
    )

    head_manifests = {path: require(git.show(head, path), path) for path in manifests}
    for path, text in head_manifests.items():
        policy.check_manifest(
            path, policy.load_manifest(require(git.show(merge_base, path), path)), policy.load_manifest(text)
        )
    base_lock_text, head_lock_text = (
        require(git.show(merge_base, lockfile), lockfile),
        require(git.show(head, lockfile), lockfile),
    )
    base_lock, head_lock = load_yaml(base_lock_text), load_yaml(head_lock_text)
    changes = policy.direct_changes(base_lock, head_lock)
    for name in sorted({name for name, _, _ in changes} | set(policy.new_packages(base_lock, head_lock))):
        if reason := policy.blocked_reason(name, blocked):
            raise Refused(reason)
    releases = sorted({(name, new) for name, old, new in changes if old != new})
    if not releases:
        raise Refused(f"{lockfile} changes no direct dependency version")
    if len(releases) > RELEASE_AGE_LOOKUPS:
        raise Refused(f"{len(releases)} packages change, more than the {RELEASE_AGE_LOOKUPS} this proof checks")
    for name, version in releases:
        if reason := policy.release_age_reason(name, version, registry(name), now):
            raise Refused(reason)

    version = policy.pnpm_version(policy.load_manifest(require(git.show(merge_base, root_manifest), root_manifest)))
    run(["npm", "install", "--global", "--no-audit", "--no-fund", f"pnpm@{version}"], worktree)
    updates = [f"{name}@{new}" for name, new in releases]
    command = replay_command(updates, bool(workspace.get("packages")), release_age_minutes())
    if comparable(replay_lockfile(worktree, directory, head_manifests, command, run)) != comparable(head_lock_text):
        raise Refused(f"pnpm writes a different {lockfile} for this update")
    return set(settings)


def load_workspace(git: Git, ref: str, directory: str) -> dict[str, Any]:
    """The pnpm-workspace.yaml beside a lockfile.

    A lockfile directory without one is refused, because pnpm would then read the settings of a
    workspace file above it, and this proof judges the directory's own.
    """
    path = join(directory, WORKSPACE_FILE)
    return load_yaml(require(git.show(ref, path), path))


def load_yaml(text: bytes) -> dict[str, Any]:
    # pnpm reads UTF-8. PyYAML given bytes would detect UTF-16 and read it, so it is given text.
    try:
        decoded = text.decode("utf-8")
    except UnicodeDecodeError as error:
        raise Refused("a YAML file is not UTF-8") from error
    # PyYAML drops a byte order mark and ends a line at U+0085, U+2028 and U+2029. pnpm's parser does neither.
    if any(character in decoded for character in ("﻿", "\x85", " ", " ")):
        raise Refused("a YAML file uses a byte order mark or a line separator that pnpm does not read")
    # pnpm never writes an alias or an explicit tag, and either would let two texts build one
    # structure. The C parser skips a Python compose hook, so the event stream is read for them.
    for event in yaml.parse(decoded, Loader=StrictLoader):
        if isinstance(event, yaml.AliasEvent) or getattr(event, "tag", None) is not None:
            raise Refused("a YAML file uses an alias or an explicit tag")
    loaded = yaml.load(decoded, Loader=StrictLoader) or {}
    if not isinstance(loaded, dict):
        raise Refused("a settings file is not a mapping")
    return loaded


def require(blob: bytes | None, path: str) -> bytes:
    if blob is None:
        raise Refused(f"{path} is missing")
    return blob


def printable(text: str) -> str:
    return re.sub(r"[^\x20-\x7e]", "?", text)


def log(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def main() -> int:
    env = os.environ
    job = sys.argv[1]
    outputs = (
        {"pr": "0", "merge_base": "", "eligible": "false"} if job == "identify" else {"files": "[]", "blobs": "{}"}
    )
    # Package names and paths from the pull request reach the log, in pnpm's output and in a refusal,
    # so the runner must not read commands from it.
    token = secrets.token_hex(16)
    log(f"::stop-commands::{token}")
    try:
        if job == "identify":
            found = identify(env, GitHub(env["REPOSITORY"], env["GITHUB_TOKEN"]))
            if found is None:
                summary = "No pull request at this head is eligible for a proof"
            else:
                outputs = {"pr": str(found.pr), "merge_base": found.merge_base, "eligible": "true"}
                summary = f"Pull request {found.pr} is eligible for a proof"
        else:
            proof = prove(env, Git(Path.cwd()), registry_metadata, run_command, datetime.now(UTC))
            outputs = {"files": json.dumps(proof.files), "blobs": json.dumps(proof.blobs)}
            summary = f"Attested {', '.join(proof.files)}" if proof.files else "Nothing to attest"
    except Refused as refusal:
        summary, failed = f"Refused: {refusal}", True
    else:
        failed = False
    log(printable(summary))
    log(f"::{token}::")
    with open(env["GITHUB_OUTPUT"], "a") as handle:
        handle.writelines(f"{key}={value}\n" for key, value in outputs.items())
    with open(env["GITHUB_STEP_SUMMARY"], "a") as handle:
        handle.write(f"### Dependency proof\n\n{printable(summary)}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
