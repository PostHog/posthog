"""Eligibility rules for a dependency update, judged with default-branch settings only."""

from __future__ import annotations

import re
import json
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

RENOVATE_BOT_USER_ID = 29139614
ALLOWED_AUTHOR_IDS = frozenset({RENOVATE_BOT_USER_ID})
MINIMUM_RELEASE_AGE = timedelta(days=7)
LOCKFILE = "pnpm-lock.yaml"
MANIFEST = "package.json"
WORKSPACE_FILE = "pnpm-workspace.yaml"
DEPENDENCY_FIELDS = ("dependencies", "devDependencies", "optionalDependencies")
# pnpm settings that name packages able to run install scripts, or exempt from a supply-chain policy.
BLOCKING_SETTINGS = (
    "allowBuilds",
    "onlyBuiltDependencies",
    "neverBuiltDependencies",
    "ignoredBuiltDependencies",
    "minimumReleaseAgeExclude",
    "trustPolicyExclude",
)
SETTINGS_FILES = (WORKSPACE_FILE, ".npmrc", ".pnpmfile.cjs", "pnpmfile.cjs")
RANGE = re.compile(r"(?P<operator>[~^]?)(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)")
# A package name with `*` wildcards. Other pattern syntax is refused, because pnpm and Renovate each read it their own way.
PACKAGE_PATTERN = re.compile(r"(@[A-Za-z0-9._~*-]+/)?[A-Za-z0-9._~*-]+")
SAFE_PATH = re.compile(r"^[A-Za-z0-9._@-]+(/[A-Za-z0-9._@-]+)*$")
PNPM_VERSION = re.compile(r"^pnpm@(\d+\.\d+\.\d+)$")


class Refused(Exception):
    """The update is outside what this proof covers. The message says why."""


def package_name(spec: str) -> str:
    """The name in `name`, `name@selector` or `@scope/name@selector`."""
    at = spec.find("@", 1)
    return spec if at < 0 else spec[:at]


def json5_loads(text: str) -> Any:
    """Parse the JSON5 subset Renovate configs use: comments, unquoted keys, single quotes, trailing commas."""
    out: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char in "\"'":
            end = i + 1
            while end < len(text) and text[end] != char:
                end += 2 if text[end] == "\\" else 1
            if end >= len(text):
                raise ValueError("unterminated string")
            body = text[i + 1 : end]
            out.append('"' + (body.replace("\\'", "'").replace('"', '\\"') if char == "'" else body) + '"')
            i = end + 1
        elif text.startswith("//", i):
            newline = text.find("\n", i)
            i = len(text) if newline < 0 else newline
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise ValueError("unterminated comment")
            i = end + 2
        elif char.isalpha() or char in "_$":
            end = i
            while end < len(text) and (text[end].isalnum() or text[end] in "_$"):
                end += 1
            after = end
            while after < len(text) and text[after].isspace():
                after += 1
            out.append(f'"{text[i:end]}"' if text.startswith(":", after) else text[i:end])
            i = end
        elif char in "}]":
            while out and out[-1] in (" ", "\t", "\n", "\r", ","):
                out.pop()
            out.append(char)
            i += 1
        else:
            out.append(char)
            i += 1
    return json.loads("".join(out))


def load_manifest(text: bytes) -> dict[str, Any]:
    """A package.json object. A repeated key is refused because readers resolve it differently."""

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        if len({key for key, _ in pairs}) != len(pairs):
            raise Refused("a package.json repeats a key")
        return dict(pairs)

    try:
        manifest = json.loads(text, object_pairs_hook=unique)
    except ValueError as error:
        raise Refused(f"a package.json is not valid JSON: {error}") from error
    if not isinstance(manifest, dict):
        raise Refused("a package.json is not an object")
    return manifest


def eligible_paths(changes: Iterable[tuple[str, str]]) -> list[str]:
    """The changed paths, when every one is a modified package.json or pnpm-lock.yaml."""
    paths = []
    for status, path in changes:
        if status != "M":
            raise Refused(f"{path} is not a modification")
        if not SAFE_PATH.match(path) or ".." in path.split("/"):
            raise Refused(f"{path} has a name this proof does not accept")
        if path.rpartition("/")[2] not in (MANIFEST, LOCKFILE):
            raise Refused(f"{path} is neither a manifest nor a lockfile")
        paths.append(path)
    if not paths:
        raise Refused("the pull request changes no files")
    return sorted(paths)


def lockfile_dir(path: str, exists: Callable[[str], bool]) -> str:
    """The nearest directory at or above a changed file that holds a lockfile. "" is the root."""
    directory = path.rpartition("/")[0]
    while True:
        if exists(join(directory, LOCKFILE)):
            return directory
        if not directory:
            raise Refused(f"{path} has no lockfile above it")
        directory = directory.rpartition("/")[0]


def is_workspace_member(directory: str, globs: list[str]) -> bool:
    """Whether pnpm-workspace.yaml `packages` globs include ``directory``, relative to the workspace root.

    pnpm includes the root itself whatever the globs say.
    """
    if not directory:
        return True
    included = excluded = False
    for glob in globs:
        negated = glob.startswith("!")
        pattern = glob.removeprefix("!").removeprefix("./").rstrip("/")
        if _glob(pattern).match(directory):
            included |= not negated
            excluded |= negated
    return included and not excluded


def _glob(pattern: str) -> re.Pattern[str]:
    parts = (re.escape(part).replace(r"\*", "[^/]*") for part in pattern.split("**"))
    return re.compile("^" + ".*".join(parts) + "$")


def check_bump(label: str, old: str, new: str) -> None:
    """Refuse anything but a same-operator registry range that moves up without a breaking change.

    A breaking change is a new major, a new minor of a 0.x version, or any new 0.0.x version.
    """
    before, after = RANGE.fullmatch(old), RANGE.fullmatch(new)
    if before is None or after is None:
        raise Refused(f"{label} changes from {old} to {new}, which is not a plain registry version change")
    old_version, new_version = (
        tuple(int(match[part]) for part in ("major", "minor", "patch")) for match in (before, after)
    )
    if before["operator"] != after["operator"] or old_version[0] != new_version[0]:
        raise Refused(f"{label} changes from {old} to {new}, which is a major change")
    if new_version[0] == 0 and old_version[1] != new_version[1]:
        raise Refused(f"{label} changes from {old} to {new}, which is a 0.x minor change")
    if new_version <= old_version:
        raise Refused(f"{label} changes from {old} to {new}, which is not an upgrade")
    if new_version[:2] == (0, 0):
        raise Refused(f"{label} changes from {old} to {new}, which is a 0.0.x change")


def manifest_changes(path: str, base: Mapping[str, Any], head: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """The (name, old range, new range) bumps in a manifest, refusing any other difference."""

    def rest(manifest: Mapping[str, Any]) -> str:
        # Compared as text, because dict equality ignores key order, which `exports` conditions depend on,
        # and reads `true` as equal to `1`.
        return json.dumps({key: value for key, value in manifest.items() if key not in DEPENDENCY_FIELDS})

    if rest(base) != rest(head):
        raise Refused(f"{path} changes more than dependency versions")
    changes = []
    for field in DEPENDENCY_FIELDS:
        before, after = base.get(field) or {}, head.get(field) or {}
        if not isinstance(before, dict) or not isinstance(after, dict) or before.keys() != after.keys():
            raise Refused(f"{path} adds or removes a package in {field}")
        for name, new in after.items():
            if before[name] != new:
                check_bump(f"{path} {name}", str(before[name]), str(new))
                changes.append((name, str(before[name]), str(new)))
    return changes


def direct_changes(base_lock: Mapping[str, Any], head_lock: Mapping[str, Any]) -> list[tuple[str, str, str, bool]]:
    """Per workspace project dependency: (name, old version, new version, specifier changed)."""
    before_importers, after_importers = base_lock.get("importers") or {}, head_lock.get("importers") or {}
    if before_importers.keys() != after_importers.keys():
        raise Refused("the lockfile adds or removes a workspace project")
    changes = []
    for importer, after in after_importers.items():
        before = before_importers[importer] or {}
        for field in DEPENDENCY_FIELDS:
            old_deps, new_deps = before.get(field) or {}, (after or {}).get(field) or {}
            if old_deps.keys() != new_deps.keys():
                raise Refused(f"{importer} adds or removes a package in {field}")
            for name, entry in new_deps.items():
                old = old_deps[name]
                if old == entry:
                    continue
                old_version, new_version = _resolved(old), _resolved(entry)
                if old_version != new_version:
                    check_bump(f"{importer} {name}", old_version, new_version)
                changes.append((name, old_version, new_version, _specifier(old) != _specifier(entry)))
    return changes


def _resolved(entry: Any) -> str:
    return str(entry.get("version", "") if isinstance(entry, dict) else "").partition("(")[0]


def _specifier(entry: Any) -> str:
    return str(entry.get("specifier", "") if isinstance(entry, dict) else "")


def new_packages(base_lock: Mapping[str, Any], head_lock: Mapping[str, Any]) -> list[str]:
    """Names of lockfile packages the update adds, each required to resolve from the registry."""
    before = base_lock.get("packages") or {}
    names = []
    for key, entry in (head_lock.get("packages") or {}).items():
        if key in before:
            continue
        if set((entry or {}).get("resolution") or {}) != {"integrity"}:
            raise Refused(f"{key} does not resolve from the registry")
        names.append(package_name(key))
    return names


def blocked_patterns(
    workspace: Mapping[str, Any], manifest: Mapping[str, Any], renovate: Mapping[str, Any], only_built_file: str | None
) -> dict[str, list[str]]:
    """Package patterns the settings exempt from a policy or allow to run scripts, keyed by setting."""
    patterns: dict[str, list[str]] = {}
    for settings in (workspace, manifest.get("pnpm") or {}):
        for key in BLOCKING_SETTINGS:
            patterns.setdefault(key, []).extend(str(entry) for entry in settings.get(key) or ())
    if only_built_file is not None:
        patterns["onlyBuiltDependenciesFile"] = [str(entry) for entry in json.loads(only_built_file)]
    for rule in renovate.get("packageRules") or []:
        if rule.get("minimumReleaseAge", "") is None:
            names = (rule.get("matchPackageNames") or []) + (rule.get("matchDepNames") or [])
            patterns.setdefault("renovate minimumReleaseAge", []).extend(names)
    return patterns


def blocked_reason(name: str, patterns: Mapping[str, Iterable[str]]) -> str | None:
    for setting, entries in patterns.items():
        for entry in entries:
            pattern = package_name(entry)
            if not PACKAGE_PATTERN.fullmatch(pattern):
                raise Refused(f"{setting} uses a pattern this proof does not read: {entry}")
            # `*` crosses `/` as it does for pnpm, and case is ignored as it is for Renovate.
            if re.fullmatch(".*".join(map(re.escape, pattern.split("*"))), name, re.IGNORECASE):
                return f"{name} is named in {setting}"
    return None


def release_age_reason(name: str, version: str, metadata: Mapping[str, Any], now: datetime) -> str | None:
    published = (metadata.get("time") or {}).get(version)
    if not isinstance(published, str):
        return f"{name}@{version} has no publish time in the registry"
    try:
        age = now - datetime.fromisoformat(published)
    except (TypeError, ValueError):
        return f"{name}@{version} has an unreadable publish time"
    if age < MINIMUM_RELEASE_AGE:
        return f"{name}@{version} was published {age.days} day(s) ago"
    return None


def settings_paths(directory: str, workspace: Mapping[str, Any]) -> list[str]:
    """Files whose head blob must equal the default branch for the proof to hold."""
    paths = [".github/renovate.json5", *SETTINGS_FILES]
    if directory:
        paths += [join(directory, name) for name in SETTINGS_FILES]
    if only_built := workspace.get("onlyBuiltDependenciesFile"):
        paths.append(join(directory, str(only_built)))
    return paths


def pnpm_version(manifest: Mapping[str, Any]) -> str:
    match = PNPM_VERSION.match(str(manifest.get("packageManager", "")))
    if match is None:
        raise Refused("the workspace does not pin an exact pnpm version in packageManager")
    return match[1]


def join(directory: str, name: str) -> str:
    return f"{directory}/{name}" if directory else name
