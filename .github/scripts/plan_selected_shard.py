"""Print the selected test files that the pytest-split item plan places on one shard.

pytest imports every file named on its command line, so a shard given every selected
file imports all of them. Each shard must pass --plan-out to pytest as --split-plan-path,
or pytest-split plans from the shard's own files and the shards disagree on shared files.
"""

import sys
import json
import argparse
from pathlib import Path

from pytest_split.algorithms import item_plan, stable_group


def plan_durations(durations: dict[str, float], files: list[str]) -> dict[str, float]:
    selected = set(files)
    return {nodeid: seconds for nodeid, seconds in durations.items() if nodeid.split("::", 1)[0] in selected}


def files_for_group(durations: dict[str, float], files: list[str], splits: int, group: int) -> list[str]:
    plan = item_plan(durations, splits)
    return [path for path in files if group - 1 in plan.file_shards.get(path, [stable_group(path, splits)])]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--durations", type=Path, required=True)
    parser.add_argument("--splits", type=int, required=True)
    parser.add_argument("--group", type=int, required=True)
    parser.add_argument("--plan-out", type=Path, required=True)
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()

    all_durations = json.loads(args.durations.read_text()) if args.durations.exists() else {}
    durations = plan_durations(all_durations, args.files)
    args.plan_out.write_text(json.dumps(durations))
    sys.stdout.write(" ".join(files_for_group(durations, args.files, args.splits, args.group)) + "\n")


if __name__ == "__main__":
    main()
