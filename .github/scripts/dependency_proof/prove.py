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
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
PULL_REQUEST_NUMBER = re.compile(r"[1-9][0-9]*")
PAGE_SIZE = 100
PROVER_FILES = (
    ".github/actions/setup-uv/action.yml",
    ".github/scripts/dependency_proof/__init__.py",
    ".github/scripts/dependency_proof/__main__.py",
    ".github/scripts/dependency_proof/policy.py",
    ".github/scripts/dependency_proof/prove.py",
    ".github/workflows/dependency-proof-trigger.yml",
    ".github/workflows/dependency-proof.yml",
    ".nvmrc",
)
# Every file pnpm reads to write a lockfile without installing.
REPLAY_FILES = (MANIFEST, LOCKFILE, WORKSPACE_FILE, ".npmrc", "*.patch")
Runner = Callable[[list[str], Path], None]


@dataclass(frozen=True)
class Unquoted:
    """A scalar that YAML reads as something other than a string, kept as the text in the file."""

    text: str

    def __str__(self) -> str:
        return self.text


class StrictLoader(YAML_LOADER):  # type: ignore[misc,valid-type]
    """Reads YAML without converting a scalar, and refuses what two parsers can read differently.

    The replay and the head lockfile are compared as the structures this loader builds, so it must
    not read two different texts as one structure. Type coercion would, because `1.10` and `1.1` are
    one float. Reading every scalar as a string would too, because pnpm reads `true` as a boolean and
    `"true"` as a string. So a string stays a `str`, a null stays `None`, and any other scalar becomes
    an `Unquoted` that holds its text. A repeated key is refused, because this parser keeps the last
    value and pnpm's may not. A scalar that spans lines is refused, because pnpm's parser joins the
    lines with other whitespace. pnpm writes one only for the `deprecated` note of a lockfile package,
    which `comparable` drops, so that one place is read.
    """

    def construct_document(self, node: yaml.Node) -> Any:
        pending: list[tuple[yaml.Node, tuple[Any, ...]]] = [(node, ())]
        while pending:
            child, path = pending.pop()
            if isinstance(child, yaml.MappingNode):
                for key, value in child.value:
                    pending += [(key, (*path, None)), (value, (*path, key.value))]
            elif isinstance(child, yaml.SequenceNode):
                pending += [(item, (*path, None)) for item in child.value]
            elif child.start_mark.line != child.end_mark.line and not (
                len(path) == 3 and path[0] == "packages" and path[2] == "deprecated"
            ):
                raise Refused("a YAML file spreads a scalar over lines")
        return super().construct_document(node)

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        if not all(isinstance(key, yaml.ScalarNode) for key, _ in node.value):
            raise Refused("a YAML file uses a key that is not a scalar")
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        if len(set(keys)) != len(keys):
            raise Refused("a YAML file repeats a key")
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
        # A new worktree copies the sparse patterns of the checkout it comes from, which hold no manifest.
        self.run("-C", str(directory), "sparse-checkout", "set", "--no-cone", *REPLAY_FILES)


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
        listed = self.get(f"commits/{head_sha}/pulls?per_page={PAGE_SIZE}")
        if len(listed) >= PAGE_SIZE:
            raise Refused("more pull requests contain this commit than this proof reads")
        return [
            pr
            for pr in listed
            if pr["state"] == "open" and pr["base"]["ref"] == base_branch and pr["head"]["sha"] == head_sha
        ]

    def pusher_id(self, branch: str, head_sha: str) -> int | None:
        """The account whose push last put the branch at this commit, or None when no listed push did."""
        ref = urllib.parse.quote(f"refs/heads/{branch}", safe="")
        pushes = self.get(f"activity?ref={ref}&per_page={PAGE_SIZE}")
        return next(((push.get("actor") or {}).get("id") for push in pushes if push["after"] == head_sha), None)

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


def replay_commands(updates: list[str], install: bool, recursive: bool) -> list[list[str]]:
    """The pnpm commands Renovate runs for one lockfile.

    Renovate runs `pnpm install` when it edits a manifest. It then runs one `pnpm update` for the
    dependencies it moves inside a range that it leaves unchanged.
    """
    flags = ["--lockfile-only", *(["--recursive"] if recursive else []), "--ignore-scripts", "--ignore-pnpmfile"]
    commands = []
    if install:
        # A runner sets `CI`, and `pnpm install` then refuses to change the lockfile without this flag.
        commands.append(["pnpm", "install", *flags, "--no-frozen-lockfile"])
    if updates:
        commands.append(["pnpm", "update", "--no-save", *updates, *flags])
    return commands


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
    worktree: Path,
    directory: str,
    head_files: Mapping[str, bytes],
    commands: list[list[str]],
    release_age_minutes: Callable[[], int],
    run: Runner,
) -> bytes:
    """The lockfile pnpm writes in the merge-base tree once the head manifests and workspace file are in place.

    `check_workspace_text` holds the head workspace file to the default branch's settings, so pnpm
    runs with those settings and the pull request's catalog.

    Each command sees the registry as Renovate saw it at the head commit. pnpm counts
    `minimumReleaseAge` back from now, so the age it gets is the policy's release age plus the time
    since the head commit. That hides everything published since the head commit, which keeps caret
    ranges and `latest` dist-tags from resolving to newer versions. A package that
    `minimumReleaseAgeExclude` names stays exempt, and `blocked_reason` refuses an update that adds
    or changes one.
    """
    for path, text in head_files.items():
        (worktree / path).write_bytes(text)
    for command in commands:
        run([*command, f"--config.minimumReleaseAge={release_age_minutes()}"], worktree / directory)
    return (worktree / join(directory, LOCKFILE)).read_bytes()


def identify(env: Mapping[str, str], github: GitHub) -> Identified | None:
    """The pull request to prove at the head named in ``env``, or None when no author there may have a proof.

    The answer depends on the head commit and not on the run. Anyone can start a run for a head,
    by reopening the pull request or by opening another one at the same commit from a fork, and
    that run reaches the same answer.
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
    if github.pusher_id(pr["head"]["ref"], head) != pr["user"]["id"]:
        raise Refused("the head commit was not pushed by the pull request author")
    return Identified(pr["number"], github.merge_base(base_branch, head))


def handed_over(env: Mapping[str, str]) -> str:
    """The merge base the identification job handed over, refused unless every value has its exact shape."""
    merge_base = env["MERGE_BASE"]
    if not PULL_REQUEST_NUMBER.fullmatch(env["PULL_REQUEST"]):
        raise Refused("the pull request number is not a positive integer")
    if not COMMIT_SHA.fullmatch(merge_base):
        raise Refused("the merge base is not a commit id")
    return merge_base


def prove(
    env: Mapping[str, str],
    git: Git,
    registry: Callable[[str], Mapping[str, Any]],
    run: Runner,
    now: datetime,
) -> Proof:
    """The proof for the pull request named in ``env``, or a Refused saying what stops it."""
    started = time.monotonic()
    head, workflow_sha = env["HEAD_SHA"], env["WORKFLOW_SHA"]
    merge_base = handed_over(env)

    git.fetch(merge_base, head)
    files = policy.eligible_paths(git.changed_files(merge_base, head))
    groups = lockfile_groups(files, git, merge_base)
    worktree = Path(env["MERGE_BASE_DIR"])
    git.add_worktree(worktree, merge_base)
    committed = git.commit_time(head)
    if committed > now:
        raise Refused("the head commit is dated in the future")

    def release_age_minutes() -> int:
        # pnpm reads its own clock when it runs, which is later than `now` by the time spent since the start.
        since_head = (now - committed).total_seconds() + time.monotonic() - started
        return int(since_head // 60) + 1 + policy.MINIMUM_RELEASE_AGE_MINUTES

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
            directory,
            manifests,
            release_age_minutes,
        )
    return Proof(files, {path: git.blob(workflow_sha, path) for path in sorted(pinned)})


def lockfile_groups(files: list[str], git: Git, merge_base: str) -> dict[str, list[str]]:
    """Changed manifests keyed by the directory of the nearest lockfile at or above them."""
    groups: dict[str, list[str]] = {}
    for path in files:
        directory = policy.lockfile_dir(path, lambda candidate: git.blob(merge_base, candidate) is not None)
        manifests = groups.setdefault(directory, [])
        name = path.rpartition("/")[2]
        if name == MANIFEST:
            manifests.append(path)
        elif name == WORKSPACE_FILE and path != join(directory, WORKSPACE_FILE):
            raise Refused(f"{path} is not beside a lockfile")
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
    directory: str,
    manifests: list[str],
    release_age_minutes: Callable[[], int],
) -> set[str]:
    """Proves one lockfile directory and returns the settings paths its proof read."""

    def read(ref: str, path: str) -> bytes:
        blob = git.show(ref, path)
        if blob is None:
            raise Refused(f"{path} is missing")
        return blob

    lockfile, root_manifest = join(directory, LOCKFILE), join(directory, MANIFEST)
    workspace_path = join(directory, WORKSPACE_FILE)
    # A lockfile directory without a workspace file is refused, because pnpm would then read the
    # settings of a workspace file above it, and this proof judges the directory's own.
    default_text, base_text, head_text = (read(ref, workspace_path) for ref in (workflow_sha, merge_base, head))
    policy.check_workspace_text(workspace_path, default_text, head_text)
    workspace = load_yaml(default_text)
    moved = policy.check_workspace(workspace_path, workspace, load_yaml(base_text), load_yaml(head_text))
    settings = policy.settings_paths(directory, workspace)
    for path in settings:
        if path != workspace_path and git.blob(head, path) != git.blob(workflow_sha, path):
            raise Refused(f"{path} differs from the default branch")
    default_manifest = policy.load_manifest(read(workflow_sha, root_manifest))
    if policy.load_manifest(read(head, root_manifest)).get("pnpm") != default_manifest.get("pnpm"):
        raise Refused(f"{root_manifest} pnpm settings differ from the default branch")
    only_built = workspace.get("onlyBuiltDependenciesFile")
    blocked = policy.blocked_patterns(
        workspace,
        default_manifest,
        read(workflow_sha, join(directory, str(only_built))).decode() if only_built else None,
    )

    base_lock, head_lock = load_yaml(read(merge_base, lockfile)), comparable(read(head, lockfile))
    head_files = {workspace_path: head_text, **{path: read(head, path) for path in manifests}}
    for path in manifests:
        policy.check_member(path, directory, base_lock)
        policy.check_manifest(
            path, policy.load_manifest(read(merge_base, path)), policy.load_manifest(head_files[path])
        )
    changes = policy.direct_changes(base_lock, head_lock)
    packages = {f"{change.name}@{change.new}" for change in changes} | set(policy.new_packages(base_lock, head_lock))
    for spec in sorted(packages):
        if reason := policy.blocked_reason(spec, blocked):
            raise Refused(reason)
    bumped = [change for change in changes if change.old != change.new]
    releases = sorted({(change.name, change.new) for change in bumped})
    if not releases:
        raise Refused(f"{lockfile} changes no direct dependency version")
    if len(releases) > RELEASE_AGE_LOOKUPS:
        raise Refused(f"{len(releases)} packages change, more than the {RELEASE_AGE_LOOKUPS} this proof checks")
    version = policy.pnpm_version(root_manifest, policy.load_manifest(read(merge_base, root_manifest)))
    for name, release in releases:
        if reason := policy.release_age_reason(name, release, registry(name), now):
            raise Refused(reason)

    run(["npm", "install", "--global", "--no-audit", "--no-fund", f"pnpm@{version}"], worktree)
    updates = sorted({f"{change.name}@{change.new}" for change in bumped if not change.range_changed})
    commands = replay_commands(updates, bool(manifests or moved), bool(workspace.get("packages")))
    replayed = replay_lockfile(worktree, directory, head_files, commands, release_age_minutes, run)
    if comparable(replayed) != head_lock:
        raise Refused(f"pnpm writes a different {lockfile} for this update")
    return set(settings)


def load_yaml(text: bytes) -> dict[str, Any]:
    # pnpm reads UTF-8. PyYAML given bytes would detect UTF-16 and read it, so it is given text.
    try:
        decoded = text.decode("utf-8")
    except UnicodeDecodeError as error:
        raise Refused("a YAML file is not UTF-8") from error
    # PyYAML drops a byte order mark and ends a line at U+0085, U+2028 and U+2029. pnpm's parser does neither.
    if any(character in decoded for character in "\N{BYTE ORDER MARK}\x85\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}"):
        raise Refused("a YAML file uses a byte order mark or a line separator that pnpm does not read")
    # pnpm never writes an alias or an explicit tag, and either would let two texts build one
    # structure. The C parser skips a Python compose hook, so the event stream is read for them.
    try:
        for event in yaml.parse(decoded, Loader=StrictLoader):
            if isinstance(event, yaml.AliasEvent) or getattr(event, "tag", None) is not None:
                raise Refused("a YAML file uses an alias or an explicit tag")
            # pnpm takes a lockfile that opens with `---` for a metadata document with the lockfile after it.
            if getattr(event, "explicit", False):
                raise Refused("a YAML file uses a document marker")
        loaded = yaml.load(decoded, Loader=StrictLoader) or {}
    except yaml.YAMLError as error:
        raise Refused("a YAML file does not parse") from error
    if not isinstance(loaded, dict):
        raise Refused("a YAML file is not a mapping")
    return loaded


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
            summary = f"Attested {', '.join(proof.files)}"
    except Refused as refusal:
        # A refusal is an answer, so the job passes. Only a failure of the prover itself fails the run.
        summary, outputs = f"Refused: {refusal}", {**outputs, "refused": "true"}
    log(printable(summary))
    log(f"::{token}::")
    with open(env["GITHUB_OUTPUT"], "a") as handle:
        handle.writelines(f"{key}={value}\n" for key, value in outputs.items())
    with open(env["GITHUB_STEP_SUMMARY"], "a") as handle:
        handle.write(f"### Dependency proof\n\n{printable(summary)}\n")
    return 0
