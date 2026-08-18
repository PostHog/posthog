# ruff: noqa: T201 allow print statements
"""Reject a restored schema dump that this checkout cannot migrate forward from.

`check-migrations` restores a cached master schema dump and then migrates up to the master it
checked out. A `restore-keys` fallback can hand it a dump built from a different master commit,
which is fine only while that commit is behind this checkout: `migrate` applies what the dump is
missing, but it never removes what the dump has and the checkout does not. So a dump from ahead of
this checkout would leave extra schema in place and make the run validate something other than
master.

Exits 1 when the database records a migration that is absent from disk, which tells the caller to
drop the dump and migrate from scratch instead.
"""

import os
import sys
from pathlib import Path

import django

# Python puts this script's own directory on sys.path, not the repo root, so `posthog` is not
# importable without this even when the job runs from the root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main() -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    django.setup()

    from django.db import connection
    from django.db.migrations.loader import MigrationLoader

    try:
        loader = MigrationLoader(connection)
    except Exception as error:
        # A dump whose graph this checkout cannot even load is one to drop, same as one that is
        # ahead. Report it as such rather than failing the job on a traceback.
        print(f"Cached dump does not load against this checkout: {error}")
        return 1

    ahead = sorted(set(loader.applied_migrations) - set(loader.disk_migrations))
    if not ahead:
        return 0

    sample = ", ".join(f"{app}.{name}" for app, name in ahead[:3])
    print(f"Cached dump records {len(ahead)} migration(s) absent from this checkout: {sample}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
