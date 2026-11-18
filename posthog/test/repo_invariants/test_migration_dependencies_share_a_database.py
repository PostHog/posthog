"""A migration may only depend on migrations that apply to every database it applies to itself.

Apps listed in `products/db_routing.yaml` migrate on their own database aliases and nowhere else.
A dependency edge across that boundary is meaningless for schema (no index or foreign key reaches
another database), and it breaks every consumer of the CI schema dump: `hogli db:restore-*`
deletes the routed apps' `django_migrations` rows from the restored default database so each
environment can apply them under its own routing, and Django's `check_consistent_history` then
refuses to migrate any database that still records a dependant of those rows.
"""

from django.db import connections, router
from django.db.migrations.loader import MigrationLoader


def _migration_aliases(app_label: str) -> frozenset[str]:
    return frozenset(alias for alias in connections if router.allow_migrate(alias, app_label))


def test_migration_dependencies_share_a_database_with_their_dependants() -> None:
    graph = MigrationLoader(connection=None, ignore_no_migrations=True).graph
    aliases = {app: _migration_aliases(app) for app in {app for app, _ in graph.nodes}}

    # The resolved graph carries `run_before` edges as parents too; the declared
    # `dependencies` list alone would miss them.
    crossings = sorted(
        f"{app}.{name} -> {parent.key[0]}.{parent.key[1]}"
        for (app, name), node in graph.node_map.items()
        for parent in node.parents
        if parent.key[0] != app and not aliases[app] <= aliases[parent.key[0]]
    )
    assert not crossings, (
        "These migrations depend on a migration that never applies to any of their own databases. "
        "Drop the dependency; a routed product app cannot be referenced from another database.\n  "
        + "\n  ".join(crossings)
    )
