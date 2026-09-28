from django.db.migrations import Migration
from django.db.migrations.loader import MigrationLoader


def _disk_migrations() -> dict[tuple[str, str], Migration]:
    loader = MigrationLoader(connection=None, load=False)
    loader.load_disk()
    return loader.disk_migrations


def test_replacing_squash_migrations_declare_no_run_before() -> None:
    offenders = sorted(
        f"{app}.{name}"
        for (app, name), migration in _disk_migrations().items()
        if migration.replaces and migration.run_before
    )
    assert not offenders, (
        "These squash migrations declare run_before while they still replace migrations. On a partially migrated "
        "database Django drops the squash and moves the run_before target onto the last replaced migration, so "
        "check_consistent_history refuses to migrate. Remove run_before; the replaced files already carry it.\n  "
        + "\n  ".join(offenders)
    )


def test_squash_same_app_dependencies_keep_a_child_outside_the_replaced_range() -> None:
    disk = _disk_migrations()
    orphaned: list[str] = []
    for (app, name), squash in sorted(disk.items()):
        if not squash.replaces:
            continue
        replaced = set(squash.replaces)
        for dependency in squash.dependencies:
            if dependency[0] != app or dependency not in disk:
                continue
            survivors = [
                key
                for key, migration in disk.items()
                if key[0] == app and key != (app, name) and key not in replaced and dependency in migration.dependencies
            ]
            if not survivors:
                orphaned.append(f"{dependency[0]}.{dependency[1]} (squash {app}.{name})")
    assert not orphaned, (
        "These migrations have the squash as their only child in their app. On a partially migrated database "
        "Django drops the squash, the migration becomes a second leaf of the app, and migrate stops with "
        "'Conflicting migrations detected'. Make a migration that runs after the squash, such as its "
        "finalize_fks tail, depend on it too.\n  " + "\n  ".join(orphaned)
    )
