"""Eligibility rules for a dependency update, judged with default-branch settings only."""

from __future__ import annotations

import re
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

RENOVATE_BOT_USER_ID = 29139614
ALLOWED_AUTHOR_IDS = frozenset({RENOVATE_BOT_USER_ID})
MINIMUM_RELEASE_AGE = timedelta(days=7)
MINIMUM_RELEASE_AGE_MINUTES = MINIMUM_RELEASE_AGE // timedelta(minutes=1)
LOCKFILE = "pnpm-lock.yaml"
MANIFEST = "package.json"
WORKSPACE_FILE = "pnpm-workspace.yaml"
CATALOG = "catalog"
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
PLAIN_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
# One line of a workspace file that gives a package a version, split into the name and the version.
VERSION_LINE = re.compile(rb"""(?P<name>[ \t]+(['"]?)[A-Za-z0-9@/._-]+\2: )[~^]?[0-9]+\.[0-9]+\.[0-9]+""")
# A package name with `*` wildcards. pnpm reads more pattern syntax, such as a leading `!`, and that is refused.
PACKAGE_PATTERN = re.compile(r"(@[A-Za-z0-9._~*-]+/)?[A-Za-z0-9._~*-]+")
SAFE_PATH = re.compile(r"^[A-Za-z0-9._@-]+(/[A-Za-z0-9._@-]+)*$")
PNPM_VERSION = re.compile(r"^pnpm@((\d+)\.\d+\.\d+)$")


class Refused(Exception):
    """The update is outside what this proof covers. The message says why."""


@dataclass(frozen=True, kw_only=True)
class DirectChange:
    """A workspace project dependency whose lockfile entry changes.

    ``old`` and ``new`` are the resolved versions. They are equal when only the range or a peer suffix changes.
    """

    name: str
    old: str
    new: str
    range_changed: bool


def package_name(spec: str) -> str:
    """The name in `name`, `name@selector` or `@scope/name@selector`."""
    at = spec.find("@", 1)
    return spec if at < 0 else spec[:at]


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
    """The changed paths, when every one is a modified package.json, pnpm-lock.yaml or pnpm-workspace.yaml."""
    paths = []
    for status, path in changes:
        if status != "M":
            raise Refused(f"{path} is not a modification")
        if not SAFE_PATH.match(path) or ".." in path.split("/"):
            raise Refused(f"{path} has a name this proof does not accept")
        if path.rpartition("/")[2] not in (MANIFEST, LOCKFILE, WORKSPACE_FILE):
            raise Refused(f"{path} is not a manifest, a lockfile or a workspace file")
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


def check_member(path: str, directory: str, lock: Mapping[str, Any]) -> None:
    """Refuse a manifest that is not a project of the lockfile in ``directory``, because no replay covers it."""
    project = path.rpartition("/")[0][len(directory) :].lstrip("/") or "."
    if project not in (lock.get("importers") or {}):
        raise Refused(f"{path} is not a project of {join(directory, LOCKFILE)}")


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
    if before["operator"] != after["operator"]:
        raise Refused(f"{label} changes from {old} to {new}, which changes the range operator")
    if old_version[0] != new_version[0]:
        raise Refused(f"{label} changes from {old} to {new}, which is a major change")
    if new_version[0] == 0 and old_version[1] != new_version[1]:
        raise Refused(f"{label} changes from {old} to {new}, which is a 0.x minor change")
    if new_version <= old_version:
        raise Refused(f"{label} changes from {old} to {new}, which is not an upgrade")
    if new_version[:2] == (0, 0):
        raise Refused(f"{label} changes from {old} to {new}, which is a 0.0.x change")


def check_manifest(path: str, base: Mapping[str, Any], head: Mapping[str, Any]) -> None:
    """Refuse a manifest that differs from its base by more than dependency range bumps."""

    def rest(manifest: Mapping[str, Any]) -> str:
        # Compared as text, because dict equality ignores key order, which `exports` conditions depend on,
        # and reads `true` as equal to `1`.
        return json.dumps({key: value for key, value in manifest.items() if key not in DEPENDENCY_FIELDS})

    if rest(base) != rest(head):
        raise Refused(f"{path} changes more than dependency versions")
    for field in DEPENDENCY_FIELDS:
        _moved_ranges(path, field, base, head)


def check_workspace_text(path: str, default: bytes, head: bytes) -> None:
    """Refuse a workspace file that differs from the default branch's by more than a catalog version.

    The settings outside ``catalog`` decide what an update may do, so the head must hold the default
    branch's. The files are compared line by line as bytes, because two YAML readers can take
    different settings from one text, and pnpm's is not the one this proof has.
    """
    default_lines, head_lines = default.split(b"\n"), head.split(b"\n")
    reason = f"{path} differs from the default branch by more than a {CATALOG} version"
    if len(default_lines) != len(head_lines):
        raise Refused(reason)
    in_catalog = False
    for trusted, line in zip(default_lines, head_lines):
        if trusted[:1].strip():
            in_catalog = trusted == f"{CATALOG}:".encode()
        if trusted == line:
            continue
        before, after = VERSION_LINE.fullmatch(trusted), VERSION_LINE.fullmatch(line)
        if not (in_catalog and before and after and before["name"] == after["name"]):
            raise Refused(reason)


def check_workspace(
    path: str, default: Mapping[str, Any], base: Mapping[str, Any], head: Mapping[str, Any]
) -> list[str]:
    """Refuse a workspace file that replays with another release age, or whose catalog does more than move ranges.

    ``default`` is the default branch's file and ``base`` is the merge base's. A catalog entry is a
    dependency range, so it is judged as a manifest's is, against the merge base.
    Returns the names of the catalog entries that move.
    """
    if str(default.get("minimumReleaseAge")) != str(MINIMUM_RELEASE_AGE_MINUTES):
        raise Refused(
            f"{path} does not set minimumReleaseAge to the {MINIMUM_RELEASE_AGE_MINUTES} minutes this proof replays with"
        )
    return _moved_ranges(path, CATALOG, base, head)


def _moved_ranges(path: str, field: str, base: Mapping[str, Any], head: Mapping[str, Any]) -> list[str]:
    """The packages whose range differs in one mapping of names to ranges, each allowed by `check_bump`."""
    before, after = base.get(field) or {}, head.get(field) or {}
    if not isinstance(before, dict) or not isinstance(after, dict) or before.keys() != after.keys():
        raise Refused(f"{path} adds or removes a package in {field}")
    moved = []
    for name, new in after.items():
        if before[name] != new:
            check_bump(f"{path} {name}", str(before[name]), str(new))
            moved.append(name)
    return moved


def direct_changes(base_lock: Mapping[str, Any], head_lock: Mapping[str, Any]) -> list[DirectChange]:
    """Each workspace project dependency whose lockfile entry or catalog range changes.

    A version may move only as `check_bump` allows.
    """
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
                range_changed = _range(base_lock, name, old) != _range(head_lock, name, entry)
                if old == entry and not range_changed:
                    continue
                old_version, new_version = _resolved(old), _resolved(entry)
                if old_version != new_version:
                    check_bump(f"{importer} {name}", old_version, new_version)
                changes.append(DirectChange(name=name, old=old_version, new=new_version, range_changed=range_changed))
    return changes


def _field(entry: Any, key: str) -> str:
    return str(entry.get(key, "") if isinstance(entry, dict) else "")


def _range(lock: Mapping[str, Any], name: str, entry: Any) -> str:
    """The range a project asks for. A `catalog:` specifier is followed to the range the lockfile records for it."""
    specifier = _field(entry, "specifier")
    if not specifier.startswith("catalog:"):
        return specifier
    catalog = (lock.get("catalogs") or {}).get(specifier.removeprefix("catalog:") or "default") or {}
    return specifier + _field(catalog.get(name), "specifier")


def _resolved(entry: Any) -> str:
    return _field(entry, "version").partition("(")[0]


def new_packages(base_lock: Mapping[str, Any], head_lock: Mapping[str, Any]) -> list[str]:
    """The `name@version` of each lockfile package the update adds, each required to resolve from the registry."""
    before = base_lock.get("packages") or {}
    added = []
    for key, entry in (head_lock.get("packages") or {}).items():
        if key in before:
            continue
        if set((entry or {}).get("resolution") or {}) != {"integrity"}:
            raise Refused(f"{key} does not resolve from the registry")
        added.append(key)
    return added


def blocked_patterns(
    workspace: Mapping[str, Any], manifest: Mapping[str, Any], only_built_file: str | None
) -> dict[str, list[str]]:
    """Package patterns the settings exempt from a policy or allow to run scripts, keyed by setting."""
    patterns: dict[str, list[str]] = {}
    for settings in (workspace, manifest.get("pnpm") or {}):
        if str(settings.get("dangerouslyAllowAllBuilds", False)).lower() != "false":
            patterns["dangerouslyAllowAllBuilds"] = ["*"]
        for key in BLOCKING_SETTINGS:
            entries = settings.get(key) or ()
            if isinstance(entries, Mapping):
                # `allowBuilds` maps a package to false to keep its scripts from running.
                entries = [entry for entry, allowed in entries.items() if str(allowed).lower() != "false"]
            elif not isinstance(entries, list | tuple):
                entries = [entries]
            patterns.setdefault(key, []).extend(str(entry) for entry in entries)
    if only_built_file is not None:
        patterns["onlyBuiltDependenciesFile"] = [str(entry) for entry in json.loads(only_built_file)]
    return patterns


def blocked_reason(spec: str, patterns: Mapping[str, Iterable[str]]) -> str | None:
    """Why the settings block a package, given as `name` or `name@version`.

    An entry that lists plain versions blocks those versions only. Any other entry blocks every
    version, and so does a package given without one.
    """
    name = package_name(spec)
    version = spec[len(name) + 1 :].partition("(")[0]
    for setting, entries in patterns.items():
        for entry in entries:
            pattern = package_name(entry)
            if not PACKAGE_PATTERN.fullmatch(pattern):
                raise Refused(f"{setting} uses a pattern this proof does not read: {entry}")
            listed = [part.strip() for part in entry[len(pattern) + 1 :].split("||")]
            if version and version not in listed and all(map(PLAIN_VERSION.fullmatch, listed)):
                continue
            # `*` crosses `/` as it does for pnpm.
            if re.fullmatch(".*".join(map(re.escape, pattern.split("*"))), name):
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
    """The files pnpm takes settings from, each of which the proof holds to the default branch."""
    paths = list(SETTINGS_FILES)
    if directory:
        paths += [join(directory, name) for name in SETTINGS_FILES]
    if only_built := workspace.get("onlyBuiltDependenciesFile"):
        paths.append(join(directory, str(only_built)))
    return paths


def pnpm_version(path: str, manifest: Mapping[str, Any]) -> str:
    match = PNPM_VERSION.match(str(manifest.get("packageManager", "")))
    if match is None:
        raise Refused(f"{path} does not pin an exact pnpm version in packageManager")
    if int(match[2]) < 11:
        raise Refused(f"{path} pins a pnpm older than 11, which can run install scripts for packages no setting names")
    return match[1]


def join(directory: str, name: str) -> str:
    return f"{directory}/{name}" if directory else name
