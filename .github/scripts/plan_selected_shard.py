"""Print the selected test files that one Django shard collects.

pytest-split's file granularity skips a file before import only when pytest walks
a directory to find it. A file named on the command line is always imported, so a
shard given every selected file imports all of them and then deselects most items.
This script gives each shard only the files that the item plan places on it.

The script also writes the plan durations to --plan-out. Each shard must pass that
file to pytest as --split-plan-path. Without it, pytest-split scopes the durations
to the shard's own command-line files, so the shards build different plans and a
file shared by two shards is not split the same way on both.
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
    group_idx = group - 1

    def collects(path: str) -> bool:
        if path in plan.file_shards:
            return group_idx in plan.file_shards[path]
        return stable_group(path, splits) == group_idx

    return [path for path in files if collects(path)]


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
