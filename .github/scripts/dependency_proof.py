# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml==6.0.3"]
# ///
"""Prove that a pull request's pnpm update is exactly the lockfile pnpm writes for it.

The dependency-proof workflow runs the base branch's copy of this script, with the base branch's
pnpm and workspace settings, so nothing the pull request changes alters how it is judged. It lists
the files it proved in a `stamphog:v1` notice, which stamphog reads as an attestation. A change it
cannot prove lists nothing and still exits 0. Only an error fails the job.
"""

import os
import re
import sys
import json
import shutil
import difflib
import secrets
import tempfile
import subprocess
import urllib.request
from collections.abc import Iterable, Mapping
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, TypedDict

import yaml


class ChangedFile(TypedDict):
    """One entry of the compare API's `files` list."""

    filename: str
    status: str


LOCKFILE = "pnpm-lock.yaml"
MANIFEST = "package.json"
DEPENDENCY_FIELDS = ("dependencies", "devDependencies", "optionalDependencies")
REGISTRY_VERSION = re.compile(r"^[~^]?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
# GitHub's compare API lists at most this many files, so a list this long may be truncated.
COMPARE_FILE_LIMIT = 300
ANNOTATION_TITLE_PREFIX = "stamphog attestation: "


def package_name(spec: str) -> str:
    """The package name in a `name` or `name@version` spec, scoped or not."""
    at = spec.rfind("@")
    return spec[:at] if at > 0 else spec


def _glob_regex(pattern: str) -> re.Pattern[str]:
    parts = (re.escape(part).replace(r"\*", "[^/]*") for part in pattern.split("**"))
    return re.compile("^" + ".*".join(parts) + "$")


def is_workspace_member(directory: str, globs: Iterable[str]) -> bool:
    """Whether pnpm-workspace.yaml's `packages` globs include ``directory`` ("" is the root)."""
    included = excluded = False
    for glob in globs:
        negated = glob.startswith("!")
        pattern = glob.removeprefix("!").removeprefix("./").rstrip("/")
        if _glob_regex("" if pattern == "." else pattern).match(directory):
            excluded |= negated
            included |= not negated
    return included and not excluded


def unprovable_file_reason(files: list[ChangedFile], member_globs: Iterable[str]) -> str | None:
    """Why the changed file list is outside what this proof covers, or None."""
    if len(files) >= COMPARE_FILE_LIMIT:
        return "the pull request changes too many files to list"
    globs = list(member_globs)
    for file in files:
        path = file["filename"]
        if file.get("status") != "modified":
            return f"{path} is {file.get('status')}, and only modified files are proved"
        directory, _, name = path.rpartition("/")
        if path != LOCKFILE and not (name == MANIFEST and is_workspace_member(directory, globs)):
            return f"{path} is neither the root lockfile nor a root workspace manifest"
    if not any(file["filename"] == LOCKFILE for file in files):
        return f"the pull request does not change {LOCKFILE}"
    return None


class _DuplicateKey(ValueError):
    pass


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    if len({key for key, _ in pairs}) != len(pairs):
        raise _DuplicateKey
    return dict(pairs)


def load_manifest(text: bytes) -> dict[str, Any] | None:
    """A package.json, or None when an object in it repeats a key."""
    try:
        return json.loads(text, object_pairs_hook=_unique_keys)
    except _DuplicateKey:
        return None


def manifest_change_reason(
    path: str, base: Mapping[str, Any], head: Mapping[str, Any], release_age_exclude: Iterable[str]
) -> str | None:
    """Why a manifest change is more than registry version bumps, or None."""

    def without_dependencies(manifest: Mapping[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in manifest.items() if key not in DEPENDENCY_FIELDS}

    if without_dependencies(base) != without_dependencies(head):
        return f"{path} changes more than dependency versions"
    excluded = list(release_age_exclude)
    for field in DEPENDENCY_FIELDS:
        before, after = base.get(field) or {}, head.get(field) or {}
        if before.keys() != after.keys():
            return f"{path} adds or removes a package in {field}"
        for name, version in after.items():
            if version == before[name]:
                continue
            if not (REGISTRY_VERSION.match(str(before[name])) and REGISTRY_VERSION.match(str(version))):
                return f"{path} changes {name} to or from a specifier that is not a registry version"
            if any(fnmatchcase(name, package_name(spec)) for spec in excluded):
                return f"{name} skips the minimum release age"
    return None


def added_package_reason(
    base_lock: Mapping[str, Any], head_lock: Mapping[str, Any], workspace: Mapping[str, Any]
) -> str | None:
    """Why a package the update adds anywhere in the graph needs a person, or None."""
    allowed_builds = {package_name(spec) for spec, allowed in (workspace.get("allowBuilds") or {}).items() if allowed}
    exemptions = {
        "the minimum release age": [package_name(spec) for spec in workspace.get("minimumReleaseAgeExclude") or []],
        "the trust policy": [package_name(spec) for spec in workspace.get("trustPolicyExclude") or []],
    }
    before = base_lock.get("packages") or {}
    for key, entry in (head_lock.get("packages") or {}).items():
        if key in before:
            continue
        name = package_name(key)
        if name in allowed_builds:
            return f"{key} runs install scripts"
        for check, patterns in exemptions.items():
            if any(fnmatchcase(name, pattern) for pattern in patterns):
                return f"{key} skips {check}"
        if set((entry or {}).get("resolution") or {}) != {"integrity"}:
            return f"{key} does not resolve from the registry"
    return None


def log(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(value: str) -> str:
    return escape_data(value).replace(":", "%3A").replace(",", "%2C")


class GitHub:
    def __init__(self, repository: str, token: str) -> None:
        self.repository = repository
        self.token = token

    def _get(self, path: str, accept: str) -> bytes:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.repository}/{path}",
            headers={"Accept": accept, "Authorization": f"Bearer {self.token}", "X-GitHub-Api-Version": "2022-11-28"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()

    def compare(self, base_sha: str, head_sha: str) -> tuple[str, list[ChangedFile]]:
        body = json.loads(self._get(f"compare/{base_sha}...{head_sha}?per_page=1", "application/vnd.github+json"))
        return body["merge_base_commit"]["sha"], body.get("files") or []

    def file(self, path: str, ref: str) -> bytes:
        return self._get(f"contents/{path}?ref={ref}", "application/vnd.github.raw")


def regenerate_lockfile(trusted: Path, head: Path, base_lockfile: bytes) -> bytes:
    """The lockfile pnpm writes from the merge-base lockfile, the head manifests and base settings."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        shutil.copy(trusted / "pnpm-workspace.yaml", work)
        if (trusted / "patches").is_dir():
            shutil.copytree(trusted / "patches", work / "patches")
        for manifest in head.rglob(MANIFEST):
            relative = manifest.relative_to(head)
            if ".git" not in relative.parts:
                (work / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(manifest, work / relative)
        (work / LOCKFILE).write_bytes(base_lockfile)
        # pnpm echoes package names from the pull request, which must not run workflow commands.
        token = secrets.token_hex(16)
        log(f"::stop-commands::{token}")
        try:
            subprocess.run(
                ["pnpm", "install", "--lockfile-only", "--ignore-scripts", "--ignore-pnpmfile", "--no-frozen-lockfile"],
                cwd=work,
                check=True,
                env={**os.environ, "pnpm_config_manage_package_manager_versions": "false"},
            )
        finally:
            log(f"::{token}::")
        return (work / LOCKFILE).read_bytes()


def prove(github: GitHub, trusted: Path, head: Path, base_sha: str, head_sha: str) -> tuple[list[str], str | None]:
    """The files proved, or none and the reason."""
    workspace = yaml.safe_load((trusted / "pnpm-workspace.yaml").read_text()) or {}
    merge_base, files = github.compare(base_sha, head_sha)
    if reason := unprovable_file_reason(files, workspace.get("packages") or []):
        return [], reason
    paths = sorted(file["filename"] for file in files)
    # pnpm never writes a symlink, and reading one would judge its target instead of the change.
    if linked := [path for path in paths if (head / path).is_symlink()]:
        return [], f"{linked[0]} is a symlink"
    for path in paths:
        if path == LOCKFILE:
            continue
        base_manifest = load_manifest(github.file(path, merge_base))
        head_manifest = load_manifest((head / path).read_bytes())
        if base_manifest is None or head_manifest is None:
            return [], f"{path} repeats a key, which readers resolve differently"
        if reason := manifest_change_reason(
            path, base_manifest, head_manifest, workspace.get("minimumReleaseAgeExclude") or []
        ):
            return [], reason
    base_lockfile = github.file(LOCKFILE, merge_base)
    head_lockfile = (head / LOCKFILE).read_bytes()
    regenerated = regenerate_lockfile(trusted, head, base_lockfile)
    if regenerated != head_lockfile:
        diff = difflib.unified_diff(
            head_lockfile.decode().splitlines(), regenerated.decode().splitlines(), "pull request", "pnpm", lineterm=""
        )
        token = secrets.token_hex(16)
        log(f"::stop-commands::{token}\n" + "\n".join(list(diff)[:60]) + f"\n::{token}::")
        return [], f"pnpm writes a different {LOCKFILE} for these manifests"
    base_lock = yaml.safe_load(base_lockfile) or {}
    head_lock = yaml.safe_load(head_lockfile) or {}
    if reason := added_package_reason(base_lock, head_lock, workspace):
        return [], reason
    return paths, None


def report(proved: list[str], reason: str | None, base_ref: str) -> None:
    marker = f"<!-- stamphog:v1 {json.dumps(proved)} -->"
    log(f"::notice title={escape_property(ANNOTATION_TITLE_PREFIX + base_ref)}::{escape_data(marker)}")
    summary = f"Proved {', '.join(proved)}." if proved else f"Proved nothing: {reason}."
    # The reason can quote a pull request's file or package name, so no newline in it may start a command.
    log(escape_data(summary))
    if summary_file := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary_file, "a") as handle:
            handle.write(f"### Dependency proof\n\n{summary}\n")


def main() -> int:
    env = os.environ
    github = GitHub(env["REPOSITORY"], env["GITHUB_TOKEN"])
    proved, reason = prove(github, Path.cwd(), Path(env["HEAD_DIR"]), env["BASE_SHA"], env["HEAD_SHA"])
    report(proved, reason, env["BASE_REF"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
