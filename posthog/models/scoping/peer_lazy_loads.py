"""Ratchet for lazy loads across peer rows on team-scoped querysets in tests.

`FETCH_RAISE_ON_PEERS` in `manager.py` asks `blocked_entry()` whether a lazy load may batch.
An entry names the model field and the code that read it, by file and function, not line:

    posthog.FeatureFlag.created_by posthog/api/feature_flag.py:FeatureFlagSerializer.get_creator

Each entry in `peer_lazy_loads_baseline.txt` still batches like production. Any other entry raises.

Set POSTHOG_PEER_LAZY_LOADS_DIR to append what a test process sees to a file in that directory.
Set POSTHOG_PEER_LAZY_LOADS=record to batch every entry instead of raising, to collect a new baseline.

This module imports nothing from Django, so CI can run it without the app installed:

    python posthog/models/scoping/peer_lazy_loads.py write <observations dir>
    python posthog/models/scoping/peer_lazy_loads.py check <observations dir> [--full-run]
"""

import os
import sys
import uuid
import argparse
from functools import cache
from pathlib import Path
from types import FrameType

MODE_ENV = "POSTHOG_PEER_LAZY_LOADS"
DIR_ENV = "POSTHOG_PEER_LAZY_LOADS_DIR"

BASELINE_PATH = Path(__file__).resolve().with_name("peer_lazy_loads_baseline.txt")
REPO_ROOT = BASELINE_PATH.parents[3]
_REPO_PREFIX = f"{REPO_ROOT}{os.sep}"
_SKIPPED_PATH_PARTS = (f"{os.sep}site-packages{os.sep}", f"{os.sep}.venv{os.sep}", f"{os.sep}.flox{os.sep}")
# The fetch mode and this module sit between the read and the code that made it.
_SKIPPED_FILES = frozenset(str(BASELINE_PATH.with_name(name)) for name in ("manager.py", "peer_lazy_loads.py"))

BASELINE_HEADER = """\
# Lazy loads across peer rows that tests still allow. See posthog/models/scoping/README.md.
# Each line is `<app_label.Model.field> <file>:<function>`. Every other such load raises FieldFetchBlocked in tests.
# Fix a site with select_related(), prefetch_related() or only(), then delete its line.
# CI fails when a line no longer happens, so this file only shrinks.
# Regenerate from CI artifacts: python posthog/models/scoping/peer_lazy_loads.py write <observations dir>
"""

BASELINED = "baselined"
BLOCKED = "blocked"


def _is_test_path(path: str) -> bool:
    name = Path(path).name
    return (
        name.startswith("test_")
        or name == "conftest.py"
        or f"{os.sep}test{os.sep}" in path
        or f"{os.sep}tests{os.sep}" in path
    )


def call_site() -> str:
    """The first repo frame outside test code, or the first repo frame when the read is in a test."""
    first: str | None = None
    frame: FrameType | None = sys._getframe(1)
    while frame is not None:
        path = frame.f_code.co_filename
        if (
            path.startswith(_REPO_PREFIX)
            and path not in _SKIPPED_FILES
            and not any(part in path for part in _SKIPPED_PATH_PARTS)
        ):
            site = f"{path[len(_REPO_PREFIX) :]}:{frame.f_code.co_qualname}"
            if not _is_test_path(path):
                return site
            first = first or site
        frame = frame.f_back
    return first or "<unknown>"


def _read_entries(path: Path) -> frozenset[str]:
    if not path.exists():
        return frozenset()
    lines = (line.strip() for line in path.read_text().splitlines())
    return frozenset(line for line in lines if line and not line.startswith("#"))


@cache
def baseline() -> frozenset[str]:
    return _read_entries(BASELINE_PATH)


def recording() -> bool:
    return os.environ.get(MODE_ENV) == "record"


class Observer:
    """Appends each status and entry once per process, so a hard exit loses nothing."""

    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()
        self._path: Path | None = None

    def observe(self, status: str, entry: str) -> None:
        directory = os.environ.get(DIR_ENV)
        if not directory or (status, entry) in self._seen:
            return
        self._seen.add((status, entry))
        if self._path is None:
            Path(directory).mkdir(parents=True, exist_ok=True)
            self._path = Path(directory) / f"peer-lazy-loads-{os.getpid()}-{uuid.uuid4().hex}.txt"
        with self._path.open("a") as out:
            out.write(f"{status}\t{entry}\n")


OBSERVER = Observer()


def blocked_entry(model_label: str, field_name: str) -> str | None:
    """Return the entry when this lazy load must raise, or None when it may batch."""
    entry = f"{model_label}.{field_name} {call_site()}"
    if entry in baseline():
        OBSERVER.observe(BASELINED, entry)
        return None
    OBSERVER.observe(BLOCKED, entry)
    return None if recording() else entry


def _observations(directory: Path) -> dict[str, set[str]]:
    seen: dict[str, set[str]] = {BASELINED: set(), BLOCKED: set()}
    for path in sorted(directory.rglob("peer-lazy-loads-*.txt")):
        for line in path.read_text().splitlines():
            status, _, entry = line.partition("\t")
            if status in seen and entry:
                seen[status].add(entry)
    return seen


def write_baseline(directory: Path, baseline_path: Path = BASELINE_PATH) -> int:
    seen = _observations(directory)
    entries = sorted(seen[BASELINED] | seen[BLOCKED])
    baseline_path.write_text(BASELINE_HEADER + "".join(f"{entry}\n" for entry in entries))
    return len(entries)


def check(directory: Path, baseline_path: Path = BASELINE_PATH, *, full_run: bool) -> list[str]:
    """Problems with the observations: loads that raised, and on a full run, entries that never happened."""
    seen = _observations(directory)
    problems: list[str] = []
    if not recording():
        problems += [f"Lazy load is not in the baseline: {entry}" for entry in sorted(seen[BLOCKED])]
    if full_run:
        # A narrowed run skips most tests, so only a full run can show that an entry is gone.
        stale = _read_entries(baseline_path) - seen[BASELINED]
        problems += [f"Baseline entry no longer happens: {entry}" for entry in sorted(stale)]
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    write_command = commands.add_parser("write", help="Write the baseline from observation files")
    write_command.add_argument("directory", type=Path)
    check_command = commands.add_parser("check", help="Fail on blocked loads and, on a full run, stale entries")
    check_command.add_argument("directory", type=Path)
    check_command.add_argument("--full-run", action="store_true", help="The run covered the whole backend suite")
    args = parser.parse_args(argv)

    if args.command == "write":
        count = write_baseline(args.directory)
        print(f"Wrote {count} entries to {BASELINE_PATH.relative_to(REPO_ROOT)}")  # noqa: T201
        return 0

    problems = check(args.directory, full_run=args.full_run)
    for problem in problems:
        print(f"::error title=Peer lazy load baseline::{problem}")  # noqa: T201
    if problems:
        print(  # noqa: T201
            "Fix a new lazy load with select_related(), prefetch_related() or only(). "
            "Delete a baseline line that no longer happens. See posthog/models/scoping/README.md."
        )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
