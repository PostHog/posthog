"""Decide whether a merge queue batch needs the full migration replay onto an empty database.

The replay finds what the primed migrate cannot: a master migration that runs with
different code, or at a different point among master's migrations, than when master
migrated from scratch. A new migration moves an old one only by pulling it in as a
dependency, and that changes the order of master's migrations relative to each other.
When master's empty-database plan is still an ordered subsequence of the batch's plan,
with every file unchanged, each master migration meets the same predecessors.
"""

import os
import sys
import hashlib
import argparse
from pathlib import Path


def empty_database_plan(repository: Path) -> list[str]:
    sys.path[:0] = [str(repository), str(repository / "common")]
    os.chdir(repository)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

    import django

    django.setup()

    from django.db.migrations.loader import MigrationLoader

    # Without a connection the loader sees no applied migrations, as on an empty database.
    graph = MigrationLoader(None, ignore_no_migrations=True).graph
    # The order MigrationExecutor.migration_plan gives `manage.py migrate` on an empty database.
    planned: dict[tuple[str, str], None] = {}
    for leaf in graph.leaf_nodes():
        planned.update(dict.fromkeys(graph.forwards_plan(leaf)))

    entries = []
    for app_label, name in planned:
        module = sys.modules[type(graph.nodes[app_label, name]).__module__]
        digest = hashlib.sha256(Path(module.__file__ or "").read_bytes()).hexdigest()
        entries.append(f"{app_label}.{name} {digest}")
    return entries


def moved_master_migration(plan: list[str], master_plan: list[str]) -> str | None:
    master_entries = set(master_plan)
    kept = [entry for entry in plan if entry in master_entries]
    for position, expected in enumerate(master_plan):
        found = kept[position] if position < len(kept) else "nothing"
        if found != expected:
            return f"position {position} of master's plan holds {found} instead of {expected}"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    # Django logs to stdout during setup, so results go to files.
    plan_command = commands.add_parser("plan", help="write the empty-database migration plan")
    plan_command.add_argument("--output", type=Path, required=True)
    check_command = commands.add_parser("check", help="set the replay output for the replay step")
    check_command.add_argument("--master-plan", type=Path, required=True)
    args = parser.parse_args()

    plan = empty_database_plan(args.repository.resolve())
    if args.command == "plan":
        args.output.write_text("\n".join(plan) + "\n")
        return

    master_plan = args.master_plan.read_text().splitlines()
    moved = moved_master_migration(plan, master_plan)
    if moved:
        sys.stderr.write(f"Replay needed: {moved}\n")
    else:
        sys.stderr.write(f"Replay skipped: {len(plan) - len(master_plan)} new migrations, master's keep their order\n")
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"replay={'true' if moved else 'false'}\n")


if __name__ == "__main__":
    main()
