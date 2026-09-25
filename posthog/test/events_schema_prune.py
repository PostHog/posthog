"""Skips events_json leg tests that a recording showed never read the native-JSON events tables.

The manifest maps each test file to a digest of its source and to the tests that are safe to skip.
A file whose digest differs from the manifest runs in full, and so does any test the manifest does
not name. Run this file as a script to build the manifest from recordings, or to check a recording
from an unpruned run against the manifest.
"""

import sys
import json
import hashlib
import argparse
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest

WHOLE_FILE = "*"
SAFE_OUTCOMES = frozenset({"passed", "skipped"})


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _split(nodeid: str) -> tuple[str, str]:
    path, _, suffix = nodeid.partition("::")
    return path, suffix


def _covers(prefix: str, suffix: str) -> bool:
    return prefix == WHOLE_FILE or suffix == prefix or suffix.startswith(f"{prefix}::")


def _scope(suffix: str) -> str:
    # Class fixtures run in the setup of a class's first test and the teardown of its last, and a
    # module-level test shares module fixtures with the whole file, so a hit outside the call phase
    # speaks for that whole scope.
    return suffix.split("::")[0] if "::" in suffix else WHOLE_FILE


def build_manifest(
    tests: Mapping[str, Mapping[str, Any]], digest_of: Callable[[str], str | None], min_seconds: float = 0.0
) -> dict[str, Any]:
    by_file: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for nodeid, record in tests.items():
        path, suffix = _split(nodeid)
        by_file[path][suffix] = record

    files: dict[str, Any] = {}
    for path, records in sorted(by_file.items()):
        digest = digest_of(path)
        if digest is None:
            continue
        shared_hits = {_scope(suffix) for suffix, record in records.items() if set(record["hits"]) - {"call"}}
        if WHOLE_FILE in shared_hits:
            continue
        safe = {
            suffix
            for suffix, record in records.items()
            if not record["hits"] and record["outcome"] in SAFE_OUTCOMES and _scope(suffix) not in shared_hits
        }
        if not safe:
            continue
        if len(safe) == len(records):
            files[path] = {"digest": digest, "prune": {WHOLE_FILE: len(records)}}
            continue
        scopes = Counter(_scope(suffix) for suffix in records)
        safe_scopes = Counter(_scope(suffix) for suffix in safe)
        prune: dict[str, int] = {}
        for suffix in sorted(safe):
            scope = _scope(suffix)
            if scope != WHOLE_FILE and safe_scopes[scope] == scopes[scope]:
                prune[scope] = scopes[scope]
            elif records[suffix]["seconds"] >= min_seconds:
                prune[suffix] = 1
        if prune:
            files[path] = {"digest": digest, "prune": prune}
    return files


def select_prunable(
    files: Mapping[str, Mapping[str, Any]], nodeids: Iterable[str], digest_of: Callable[[str], str | None]
) -> set[str]:
    suffixes_by_file: dict[str, list[str]] = defaultdict(list)
    for nodeid in nodeids:
        path, suffix = _split(nodeid)
        if path in files:
            suffixes_by_file[path].append(suffix)

    prunable: set[str] = set()
    for path, suffixes in suffixes_by_file.items():
        entry = files[path]
        if digest_of(path) != entry["digest"]:
            continue
        for prefix, recorded_count in entry["prune"].items():
            covered = [suffix for suffix in suffixes if _covers(prefix, suffix)]
            # A count that no longer matches means collection produced tests the recording never
            # saw, for example parameters read from a data file, so the whole scope runs.
            if len(covered) == recorded_count:
                prunable.update(f"{path}::{suffix}" for suffix in covered)
    return prunable


def listed_tests_that_hit(
    files: Mapping[str, Mapping[str, Any]],
    tests: Mapping[str, Mapping[str, Any]],
    digest_of: Callable[[str], str | None],
) -> list[str]:
    stale = []
    for nodeid, record in tests.items():
        path, suffix = _split(nodeid)
        entry = files.get(path)
        if (
            record["hits"]
            and entry is not None
            and digest_of(path) == entry["digest"]
            and any(_covers(prefix, suffix) for prefix in entry["prune"])
        ):
            stale.append(nodeid)
    return sorted(stale)


def digests_under(root: Path) -> Callable[[str], str | None]:
    def digest_of(path: str) -> str | None:
        source = root / path
        return file_digest(source) if source.is_file() else None

    return digest_of


class EventsSchemaPruner:
    def __init__(self, manifest: Path) -> None:
        self._files = json.loads(manifest.read_text())["files"]

    # tryfirst so pytest-split, which runs trylast, shards only the tests that remain.
    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(self, config: pytest.Config, items: list[pytest.Item]) -> None:
        prunable = select_prunable(self._files, (item.nodeid for item in items), digests_under(config.rootpath))
        if not prunable:
            return
        config.hook.pytest_deselected(items=[item for item in items if item.nodeid in prunable])
        items[:] = [item for item in items if item.nodeid not in prunable]


def _load_tests(recordings: Iterable[Path]) -> dict[str, Any]:
    tests: dict[str, Any] = {}
    for recording in recordings:
        data = json.loads(recording.read_text())
        if not data["events_json_mode"] or data["json_table_readers"] != []:
            raise SystemExit(f"{recording} cannot prove tests independent: {data['json_table_readers']}")
        tests.update(data["tests"])
    return tests


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Write a manifest from the recordings of a full events_json run.")
    build.add_argument("--source", required=True, help="The CI run that produced the recordings.")
    build.add_argument("--output", type=Path, required=True)
    build.add_argument(
        "--min-seconds",
        type=float,
        default=0.1,
        help="List a single test only when it took at least this long, so the manifest stays reviewable.",
    )
    build.add_argument("recordings", type=Path, nargs="+")
    check = commands.add_parser("check", help="Fail when a test the manifest skips read the JSON tables.")
    check.add_argument("manifest", type=Path)
    check.add_argument("recordings", type=Path, nargs="+")
    args = parser.parse_args(argv)

    digest_of = digests_under(Path.cwd())
    tests = _load_tests(args.recordings)
    if args.command == "build":
        files = build_manifest(tests, digest_of, args.min_seconds)
        args.output.write_text(json.dumps({"source": args.source, "files": files}, indent=1, sort_keys=True) + "\n")
        skipped = len(select_prunable(files, tests, digest_of))
        sys.stdout.write(f"{len(files)} files, {skipped} of {len(tests)} recorded tests skipped\n")
        return 0

    files = json.loads(args.manifest.read_text())["files"]
    stale = listed_tests_that_hit(files, tests, digest_of)
    for nodeid in stale:
        sys.stdout.write(f"::error::{nodeid} reads the events_json tables but {args.manifest} skips it. Rebuild it.\n")
    changed = sum(digest_of(path) != entry["digest"] for path, entry in files.items())
    if changed:
        sys.stdout.write(
            f"::notice::{changed} files changed since {args.manifest} was built, so all their tests run.\n"
        )
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
