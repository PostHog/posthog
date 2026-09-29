"""Skips events_json leg tests that a recording showed never read the native-JSON events tables.

The manifest maps each test file to a digest of its source and to the tests that are safe to skip.
A file whose digest differs from the manifest runs in full, and so does any test the manifest does
not name. Run this file as a script, from a checkout of the recorded commit, to build the manifest
from the recordings of an unpruned run.
"""

import sys
import json
import hashlib
import argparse
import functools
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import TypedDict

import pytest

WHOLE_FILE = "*"
# A skipped or expected-to-fail test did not run its assertions in the recording, so it proves nothing.
PROVEN_OUTCOME = "passed"
# The recorder names the fixture scope of a setup hit. A module-scoped fixture, and a setup or
# teardown hit with no recorded scope, can feed every test in the file.
TEST_PHASES = frozenset({"call", "setup:function"})
CLASS_PHASES = frozenset({"setup:class"})
UNBOUNDED_PHASES = frozenset({"setup:package", "setup:session"})


class RecordedTest(TypedDict):
    hits: dict[str, int]
    seconds: float
    outcome: str


class ManifestEntry(TypedDict):
    digest: str
    prune: dict[str, str]


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def ids_digest(suffixes: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(suffixes)).encode()).hexdigest()[:12]


def _split(nodeid: str) -> tuple[str, str]:
    path, _, suffix = nodeid.partition("::")
    return path, suffix


def _covers(prefix: str, suffix: str) -> bool:
    return prefix == WHOLE_FILE or suffix == prefix or suffix.startswith(f"{prefix}::")


def _class_of(suffix: str) -> str:
    return suffix.split("::")[0] if "::" in suffix else WHOLE_FILE


def _hit_prefix(nodeid: str, phase: str) -> str:
    suffix = _split(nodeid)[1]
    if phase in UNBOUNDED_PHASES:
        raise ValueError(f"{nodeid} read the JSON tables in a {phase} fixture, which any test file can share")
    if phase in TEST_PHASES:
        return suffix
    if phase in CLASS_PHASES:
        return _class_of(suffix)
    return WHOLE_FILE


def safe_nodeids(tests: Mapping[str, RecordedTest]) -> set[str]:
    blocked: dict[str, set[str]] = defaultdict(set)
    for nodeid, record in tests.items():
        for phase in record["hits"]:
            blocked[_split(nodeid)[0]].add(_hit_prefix(nodeid, phase))
    return {
        nodeid
        for nodeid, record in tests.items()
        if record["outcome"] == PROVEN_OUTCOME
        and not any(_covers(prefix, _split(nodeid)[1]) for prefix in blocked[_split(nodeid)[0]])
    }


def build_manifest(
    tests: Mapping[str, RecordedTest], digest_of: Callable[[str], str | None]
) -> dict[str, ManifestEntry]:
    safe = safe_nodeids(tests)
    by_file: dict[str, dict[str, RecordedTest]] = defaultdict(dict)
    for nodeid, record in tests.items():
        path, suffix = _split(nodeid)
        by_file[path][suffix] = record

    files: dict[str, ManifestEntry] = {}
    for path, records in sorted(by_file.items()):
        digest = digest_of(path)
        safe_suffixes = {suffix for suffix in records if f"{path}::{suffix}" in safe}
        if digest is None or not safe_suffixes:
            continue
        if len(safe_suffixes) == len(records):
            files[path] = {"digest": digest, "prune": {WHOLE_FILE: ids_digest(records)}}
            continue
        class_sizes = Counter(_class_of(suffix) for suffix in records)
        safe_class_sizes = Counter(_class_of(suffix) for suffix in safe_suffixes)
        prune: dict[str, str] = {}
        for suffix in sorted(safe_suffixes):
            cls = _class_of(suffix)
            if cls != WHOLE_FILE and safe_class_sizes[cls] == class_sizes[cls]:
                prune[cls] = ids_digest(s for s in records if _covers(cls, s))
            else:
                prune[suffix] = ids_digest([suffix])
        files[path] = {"digest": digest, "prune": prune}
    return files


def select_prunable(
    files: Mapping[str, ManifestEntry], nodeids: Iterable[str], digest_of: Callable[[str], str | None]
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
        for prefix, recorded_ids in entry["prune"].items():
            covered = [suffix for suffix in suffixes if _covers(prefix, suffix)]
            # Collection can produce tests the recording never saw without a change to the test
            # file, for example parameters read from a data file. Then the whole scope runs.
            if ids_digest(covered) == recorded_ids:
                prunable.update(f"{path}::{suffix}" for suffix in covered)
    return prunable


def digests_under(root: Path) -> Callable[[str], str | None]:
    @functools.cache
    def digest_of(path: str) -> str | None:
        source = root / path
        return file_digest(source) if source.is_file() else None

    return digest_of


class EventsSchemaPruner:
    def __init__(self, manifest: Path) -> None:
        self._files: dict[str, ManifestEntry] = json.loads(manifest.read_text())["files"]

    # tryfirst so pytest-split, which runs trylast, shards only the tests that remain.
    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(self, config: pytest.Config, items: list[pytest.Item]) -> None:
        prunable = select_prunable(self._files, (item.nodeid for item in items), digests_under(config.rootpath))
        if not prunable:
            return
        # syrupy records collected tests in its own later hook. A test it never sees counts as deleted,
        # so an unsplit --snapshot-update run would remove that test's snapshots.
        if syrupy_session := getattr(config, "_syrupy", None):
            syrupy_session.collect_items(items)
        config.hook.pytest_deselected(items=[item for item in items if item.nodeid in prunable])
        items[:] = [item for item in items if item.nodeid not in prunable]


def merge_records(first: RecordedTest, second: RecordedTest) -> RecordedTest:
    hits = Counter(first["hits"]) + Counter(second["hits"])
    outcomes = {first["outcome"], second["outcome"]} - {PROVEN_OUTCOME}
    return {
        "hits": dict(hits),
        "outcome": min(outcomes) if outcomes else PROVEN_OUTCOME,
        "seconds": max(first["seconds"], second["seconds"]),
    }


def _load_tests(recordings: Iterable[Path]) -> dict[str, RecordedTest]:
    tests: dict[str, RecordedTest] = {}
    for recording in recordings:
        data = json.loads(recording.read_text())
        if not data["events_json_mode"] or data["json_table_readers"] != []:
            raise ValueError(f"{recording} cannot prove tests independent: {data['json_table_readers']}")
        for nodeid, record in data["tests"].items():
            tests[nodeid] = merge_records(tests[nodeid], record) if nodeid in tests else record
    return tests


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("recordings", type=Path, nargs="+")
    args = parser.parse_args(argv)

    digest_of = digests_under(Path.cwd())
    try:
        tests = _load_tests(args.recordings)
        files = build_manifest(tests, digest_of)
    except ValueError as error:
        sys.stdout.write(f"::error::{error}\n")
        return 1
    args.output.write_text(json.dumps({"files": files}))
    skipped = len(select_prunable(files, tests, digest_of))
    sys.stdout.write(f"{len(files)} files, {skipped} of {len(tests)} recorded tests skipped\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
