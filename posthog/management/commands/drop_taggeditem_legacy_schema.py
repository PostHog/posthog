"""Drop the legacy tagged item constraints and foreign keys, one lock at a time.

Migration 1376 tried this inside `bin/migrate` and deadlocked in prod-eu: a single
transaction dropped every constraint and every foreign key, taking ACCESS EXCLUSIVE on the
child before each parent, while application queries take their locks parent first.

This command does the same work from a toolbox pod, under an operator's eye, one object per
transaction. Each attempt takes its locks through `lock_tables`, which orders parents before
the child and abandons the wait under a budget below `deadlock_timeout`, so a lock race ends
with this command giving up rather than a customer query being killed. Nothing here waits
long enough to queue the table behind it.

Run it once per region before the release that stops writing the legacy keys. It is
idempotent: it reads what is left out of the catalog on every pass, so a re-run after a
partial failure picks up exactly what remains.

    python manage.py drop_taggeditem_legacy_schema --dry-run
    python manage.py drop_taggeditem_legacy_schema
"""

import time
from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from posthog.dataclasses import frozen
from posthog.migration_helpers.lock_phase import lock_tables

TABLE = "posthog_taggeditem"

LEGACY_FIELDS = (
    "dashboard",
    "insight",
    "event_definition",
    "property_definition",
    "action",
    "feature_flag",
    "experiment_saved_metric",
    "ticket",
    "account",
    "endpoint",
    "replay_scanner",
    "project",
    "experiment",
)

# Indexes and constraints this repository named itself, so the names cannot drift.
PARTIAL_UNIQUE_INDEXES = tuple(f"unique_{field}_tagged_item" for field in LEGACY_FIELDS)
CHECK_CONSTRAINT = "exactly_one_related_object"

UNIQUE_TOGETHER_SQL = """
    SELECT con.conname
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    WHERE rel.relname = %s AND con.contype = 'u' AND array_length(con.conkey, 1) = 14
"""

FOREIGN_KEYS_SQL = """
    SELECT con.conname, parent.relname
    FROM pg_constraint con
    JOIN pg_class child ON child.oid = con.conrelid
    JOIN pg_class parent ON parent.oid = con.confrelid
    JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ANY(con.conkey)
    WHERE con.contype = 'f' AND child.relname = %s AND att.attname = ANY(%s)
    ORDER BY con.conname
"""

INDEX_EXISTS_SQL = "SELECT 1 FROM pg_class WHERE relkind = 'i' AND relname = %s"
CONSTRAINT_EXISTS_SQL = """
    SELECT 1
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    WHERE rel.relname = %s AND con.conname = %s
"""


@frozen
class _PendingDrop:
    """One object still on the table, and the locks its drop needs."""

    label: str
    """What the operator sees, for example `foreign key ... -> posthog_dashboard`."""

    sql: str
    """The statement that drops it."""

    parents: tuple[str, ...]
    """Tables to lock before the child, in the order a joining query locks them."""


class _SchemaEditorShim:
    """The two methods `lock_tables` needs, over a plain connection."""

    def __init__(self, db_connection: Any) -> None:
        self.connection = db_connection

    def execute(self, sql: str, params: Any = None) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)

    def quote_name(self, name: str) -> str:
        return self.connection.ops.quote_name(name)


class Command(BaseCommand):
    help = "Drop the legacy TaggedItem constraints and foreign keys, one lock at a time."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="List what is left and exit.")
        parser.add_argument("--attempts", type=int, default=25, help="Attempts per object before giving up.")
        parser.add_argument("--pause", type=float, default=2.0, help="Seconds between attempts.")

    def handle(self, *args: Any, **options: Any) -> None:
        editor = _SchemaEditorShim(connection)
        remaining = self._remaining()

        if not remaining:
            self.stdout.write(self.style.SUCCESS("Nothing left to drop."))
            return

        self.stdout.write(f"{len(remaining)} objects left on {TABLE}:")
        for pending in remaining:
            locked = ", ".join([*pending.parents, TABLE])
            self.stdout.write(f"  {pending.label}  (locks: {locked})")

        if options["dry_run"]:
            return

        failed: list[str] = []
        for pending in remaining:
            if self._drop(editor, pending, options["attempts"], options["pause"]):
                self.stdout.write(self.style.SUCCESS(f"dropped {pending.label}"))
            else:
                failed.append(pending.label)
                self.stdout.write(self.style.WARNING(f"gave up on {pending.label}, re-run to retry"))

        if failed:
            self.stdout.write(self.style.WARNING(f"{len(failed)} left: {', '.join(failed)}"))
        else:
            self.stdout.write(self.style.SUCCESS("All legacy constraints and foreign keys are gone."))

    def _drop(self, editor: Any, pending: _PendingDrop, attempts: int, pause: float) -> bool:
        """One object, one transaction per attempt. A lost lock race costs nothing."""
        for attempt in range(1, attempts + 1):
            try:
                with transaction.atomic():
                    lock_tables(editor, [*pending.parents, TABLE])
                    editor.execute(pending.sql)
                return True
            except Exception as error:  # noqa: BLE001 — a lost lock race is the expected case
                self.stdout.write(f"  {pending.label}: attempt {attempt}/{attempts} did not get the lock ({error})")
                time.sleep(pause)
        return False

    def _remaining(self) -> list[_PendingDrop]:
        """What is still on the table, in the order it is safe to drop."""
        remaining: list[_PendingDrop] = []

        with connection.cursor() as cursor:
            for index in PARTIAL_UNIQUE_INDEXES:
                cursor.execute(INDEX_EXISTS_SQL, [index])
                if cursor.fetchone():
                    remaining.append((f"index {index}", f"DROP INDEX {connection.ops.quote_name(index)}", []))

            cursor.execute(CONSTRAINT_EXISTS_SQL, [TABLE, CHECK_CONSTRAINT])
            if cursor.fetchone():
                remaining.append(
                    _PendingDrop(
                        label=f"check {CHECK_CONSTRAINT}",
                        sql=self._drop_constraint(CHECK_CONSTRAINT),
                        parents=(),
                    )
                )

            cursor.execute(UNIQUE_TOGETHER_SQL, [TABLE])
            for (name,) in cursor.fetchall():
                remaining.append(
                    _PendingDrop(label=f"unique_together {name}", sql=self._drop_constraint(name), parents=())
                )

            cursor.execute(FOREIGN_KEYS_SQL, [TABLE, [f"{field}_id" for field in LEGACY_FIELDS]])
            for name, parent in cursor.fetchall():
                # A key that references its own table names the child as its parent, and the
                # child is locked last either way.
                remaining.append(
                    _PendingDrop(
                        label=f"foreign key {name} -> {parent}",
                        sql=self._drop_constraint(name),
                        parents=() if parent == TABLE else (parent,),
                    )
                )

        return remaining

    @staticmethod
    def _drop_constraint(name: str) -> str:
        return f"ALTER TABLE {connection.ops.quote_name(TABLE)} DROP CONSTRAINT {connection.ops.quote_name(name)}"
