"""A squash migration must not declare `run_before` while it still replaces migrations.

On a database that applied only part of a squash's replaced range, Django's loader drops the
squash and moves every child of the squash onto the last replaced migration. A `run_before`
target is such a child. The target is usually applied long before the end of the range, so
`check_consistent_history` then finds an applied migration with an unapplied dependency and
refuses to migrate. The replaced files carry the same `run_before` entries, and the loader moves
them onto the squash when it substitutes, so the squash needs its own copy only after the
replaced files are deleted and `replaces` is empty.
"""

from django.db.migrations.loader import MigrationLoader


def test_replacing_squash_migrations_declare_no_run_before() -> None:
    loader = MigrationLoader(connection=None, load=False)
    loader.load_disk()

    offenders = sorted(
        f"{app}.{name}"
        for (app, name), migration in loader.disk_migrations.items()
        if migration.replaces and migration.run_before
    )
    assert not offenders, (
        "These squash migrations declare run_before while they still replace migrations, which breaks "
        "every partially migrated database. Remove run_before; the replaced files already carry it.\n  "
        + "\n  ".join(offenders)
    )
