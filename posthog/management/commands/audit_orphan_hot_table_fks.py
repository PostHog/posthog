"""Report tables that hold a foreign key to a hot parent but have no Django model.

A model retired with SeparateDatabaseAndState(state_operations=[...]) leaves its table in
the database. When that table keeps a foreign key to posthog_team, posthog_user,
posthog_organization or posthog_project, deleting a parent row cascades in Django but never
clears the orphaned child rows, so the delete fails at COMMIT on the deferred constraint.

This command reads the connected database rather than the migration files. A squashed history
drops the CreateModel operations for tables that left Django's state before the squash, so a
fresh database never creates them and static analysis cannot see them. Only a long-lived
database still carries them.
"""

from typing import Any

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

HOT_PARENT_TABLES = (
    "posthog_team",
    "posthog_user",
    "posthog_organization",
    "posthog_project",
)

# confdeltype 'a' (NO ACTION) and 'r' (RESTRICT) make the parent delete fail while a child row
# survives. 'c' (CASCADE), 'n' (SET NULL) and 'd' (SET DEFAULT) let Postgres clear the child row
# on its own, so they do not block a delete even when Django cannot see the table.
BLOCKING_DELETE_ACTIONS = ("a", "r")

ORPHAN_FK_QUERY = """
    SELECT src.relname   AS referencing_table,
           con.conname   AS constraint_name,
           tgt.relname   AS referenced_table,
           con.condeferred,
           con.confdeltype
    FROM pg_constraint con
    JOIN pg_class src ON src.oid = con.conrelid
    JOIN pg_class tgt ON tgt.oid = con.confrelid
    JOIN pg_namespace ns ON ns.oid = src.relnamespace
    WHERE con.contype = 'f'
      AND ns.nspname = 'public'
      AND tgt.relname = ANY(%s)
      AND con.confdeltype = ANY(%s)
    ORDER BY src.relname, con.conname
"""


def known_django_tables() -> set[str]:
    return {model._meta.db_table.lower() for model in apps.get_models(include_auto_created=True)}


def find_orphan_fks() -> list[dict[str, Any]]:
    """Foreign keys that block a hot-parent delete and whose owning table has no Django model."""
    known = known_django_tables()
    with connection.cursor() as cursor:
        cursor.execute(ORPHAN_FK_QUERY, [list(HOT_PARENT_TABLES), list(BLOCKING_DELETE_ACTIONS)])
        rows = cursor.fetchall()
    return [
        {
            "referencing_table": referencing,
            "constraint_name": constraint,
            "referenced_table": referenced,
            "deferred": deferred,
            "delete_action": delete_action,
        }
        for referencing, constraint, referenced, deferred, delete_action in rows
        if referencing.lower() not in known
    ]


class Command(BaseCommand):
    help = "Report tables with a foreign key to a hot parent table but no Django model"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--fail-on-findings",
            action="store_true",
            help="Exit non-zero when an orphan is found, for use in a scheduled check",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        orphans = find_orphan_fks()
        if not orphans:
            self.stdout.write(self.style.SUCCESS("No orphaned foreign keys to hot parent tables."))
            return

        tables = sorted({row["referencing_table"] for row in orphans})
        self.stdout.write(
            self.style.WARNING(f"{len(tables)} table(s) with no Django model hold a foreign key to a hot parent:")
        )
        for row in orphans:
            deferred = "deferred" if row["deferred"] else "immediate"
            self.stdout.write(
                f"  {row['referencing_table']} -> {row['referenced_table']}  ({row['constraint_name']}, {deferred})"
            )
        self.stdout.write(
            "\nEach one blocks deletion of a parent row whose children live in that table. "
            "Drop the table, or drop the foreign key, following safe-django-migrations.md."
        )
        if options["fail_on_findings"]:
            raise CommandError(f"{len(tables)} orphaned table(s) hold a foreign key to a hot parent")
