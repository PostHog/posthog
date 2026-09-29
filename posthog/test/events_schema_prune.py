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
import functools
import subprocess
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
    return content_digest(path.read_bytes())


def content_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:16]


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
    tests: Mapping[str, RecordedTest], digest_of: Callable[[str], str | None], min_seconds: float = 0.0
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
            elif records[suffix]["seconds"] >= min_seconds:
                prune[suffix] = ids_digest([suffix])
        if prune:
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


def stale_entries(
    files: Mapping[str, ManifestEntry],
    tests: Mapping[str, RecordedTest],
    digest_of: Callable[[str], str | None],
) -> list[str]:
    # Each shard checks only the tests it ran, so a listed test counts whether or not the rest of
    # its scope ran in the same shard.
    def listed(nodeid: str) -> bool:
        path, suffix = _split(nodeid)
        entry = files.get(path)
        return (
            entry is not None
            and digest_of(path) == entry["digest"]
            and any(_covers(prefix, suffix) for prefix in entry["prune"])
        )

    return sorted(nodeid for nodeid in set(tests) - safe_nodeids(tests) if listed(nodeid))


def digests_under(root: Path) -> Callable[[str], str | None]:
    @functools.cache
    def digest_of(path: str) -> str | None:
        source = root / path
        return file_digest(source) if source.is_file() else None

    return digest_of


def digests_at(revision: str) -> Callable[[str], str | None]:
    @functools.cache
    def digest_of(path: str) -> str | None:
        shown = subprocess.run(["git", "show", f"{revision}:{path}"], capture_output=True, check=False)
        return content_digest(shown.stdout) if shown.returncode == 0 else None

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


def rebuild_command(manifest: Path, run_id: str, revision: str) -> str:
    return (
        f"gh run download {run_id} --repo PostHog/posthog --pattern 'events-schema-record-*' --dir events-schema-records"
        f" && python posthog/test/events_schema_prune.py build --revision {revision}"
        f" --source https://github.com/PostHog/posthog/actions/runs/{run_id}"
        f" --output {manifest} events-schema-records/*/events-schema-record.json"
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Write a manifest from the recordings of an unpruned events_json run.")
    build.add_argument("--source", required=True, help="The CI run that produced the recordings.")
    build.add_argument("--revision", help="The commit the run tested. Defaults to the working tree.")
    build.add_argument("--output", type=Path, required=True)
    build.add_argument(
        "--min-seconds",
        type=float,
        default=0.1,
        help="List a single test only when it took at least this long, so the manifest stays reviewable.",
    )
    build.add_argument("recordings", type=Path, nargs="+")
    check = commands.add_parser("check", help="Fail when a test the manifest skips is no longer independent.")
    check.add_argument("--run-id", required=True, help="The CI run that produced the recordings.")
    check.add_argument("--revision", required=True, help="The commit the run tested.")
    check.add_argument("manifest", type=Path)
    check.add_argument("recordings", type=Path, nargs="+")
    args = parser.parse_args(argv)

    try:
        tests = _load_tests(args.recordings)
        if args.command == "build":
            digest_of = digests_at(args.revision) if args.revision else digests_under(Path.cwd())
            files = build_manifest(tests, digest_of, args.min_seconds)
            args.output.write_text(json.dumps({"source": args.source, "files": files}, indent=1, sort_keys=True) + "\n")
            skipped = len(select_prunable(files, tests, digest_of))
            sys.stdout.write(f"{len(files)} files, {skipped} of {len(tests)} recorded tests skipped\n")
            return 0
        digest_of = digests_under(Path.cwd())
        files = json.loads(args.manifest.read_text())["files"]
        stale = stale_entries(files, tests, digest_of)
    except ValueError as error:
        sys.stdout.write(f"::error::{error}\n")
        return 1
    for nodeid in stale:
        sys.stdout.write(f"::error::{args.manifest} skips {nodeid}, which read the events_json tables or failed.\n")
    if stale:
        sys.stdout.write(
            f"::error::Rebuild the manifest after this run finishes: {rebuild_command(args.manifest, args.run_id, args.revision)}\n"
        )
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
