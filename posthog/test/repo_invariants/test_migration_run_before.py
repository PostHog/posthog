"""A migration that declares `run_before` must name a target.

`run_before = []` is the same as not declaring the attribute, so it is always a leftover: a
migration that needs an ordering edge silently loses it, and the comment above the line keeps
telling the reader the edge is there. Django reports nothing, and the planner is then free to
apply the two migrations in either order.
"""

from django.db.migrations.loader import MigrationLoader


def test_declared_run_before_names_a_target() -> None:
    loader = MigrationLoader(connection=None, load=False)
    loader.load_disk()
    offenders = sorted(
        f"{app}.{name}"
        for (app, name), migration in loader.disk_migrations.items()
        if "run_before" in type(migration).__dict__ and not migration.run_before
    )
    assert not offenders, (
        "These migrations declare an empty run_before. Name the migration this one must run "
        "before, or delete the attribute.\n  " + "\n  ".join(offenders)
    )
