"""A database that applied only part of a squash's replaced range must still migrate.

On such a database Django's loader drops the squash and uses the replaced files. It moves every
child of the squash onto the last replaced migration, and every edge the squash declares is gone.
Two rules keep that fallback graph valid:

- A squash declares no `run_before` while it still replaces migrations. A `run_before` target is a
  child of the squash, so it moves onto the last replaced migration. The target is usually applied
  long before the end of the range, and `check_consistent_history` refuses to migrate. The replaced
  files carry the same entries, and the loader moves them onto the squash when it substitutes.
- Every replaced root depends on each same-app migration the squash depends on, such as the stub.
  The squash is the only same-app child of the stub. Without it the stub becomes a second leaf of
  the app, and `migrate` stops with "Conflicting migrations detected".
"""

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
        "These squash migrations declare run_before while they still replace migrations, which breaks "
        "every partially migrated database. Remove run_before; the replaced files already carry it.\n  "
        + "\n  ".join(offenders)
    )


def test_replaced_roots_depend_on_the_squash_same_app_dependencies() -> None:
    disk = _disk_migrations()
    missing: list[str] = []
    for (app, name), squash in sorted(disk.items()):
        replaced = set(squash.replaces)
        same_app_dependencies = [dep for dep in squash.dependencies if dep[0] == app]
        for root in sorted(replaced):
            if root not in disk or any(dep in replaced for dep in disk[root].dependencies):
                continue
            missing.extend(
                f"{root[0]}.{root[1]} -> {dep[0]}.{dep[1]} (squash {app}.{name})"
                for dep in same_app_dependencies
                if dep not in disk[root].dependencies
            )
    assert not missing, (
        "These replaced root migrations lack a dependency of the squash that replaces them. A partially "
        "migrated database then has a second leaf in the app. Add the dependency to the root migration.\n  "
        + "\n  ".join(missing)
    )
