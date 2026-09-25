"""Functional tests for DropColumnConstraints.

Each test builds a real table whose rules carry hash-suffixed names, the way Django and
earlier constraint swaps leave them, so the catalog lookup is the only way to find them.
"""

import uuid

import pytest

from django.db import connection

from posthog.migration_helpers import DropColumnConstraints


@pytest.fixture
def temp_table():
    suffix = uuid.uuid4().hex[:8]
    parent = f"test_dropcc_parent_{suffix}"
    table = f"test_dropcc_{suffix}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE TABLE "{parent}" (id serial primary key)')
        cursor.execute(
            f"""
            CREATE TABLE "{table}" (
                id serial primary key,
                tag_id int NOT NULL,
                keeper_id int,
                legacy_a_id int CONSTRAINT "{table}_legacy_a_id_1c2d3e4f_fk" REFERENCES "{parent}"(id),
                legacy_b_id int,
                CONSTRAINT "{table}_tag_id_legacy_a_id_9f8e7d6c_uniq" UNIQUE (tag_id, legacy_a_id, legacy_b_id),
                CONSTRAINT "exactly_one_legacy_key" CHECK ((legacy_a_id IS NULL) <> (legacy_b_id IS NULL)),
                CONSTRAINT "keeper_positive" CHECK (keeper_id > 0)
            )
            """
        )
        cursor.execute(
            f'CREATE UNIQUE INDEX "{table}_tag_id_legacy_a_id_5a6b7c8d_uniq" ON "{table}" (tag_id, legacy_a_id)'
        )
        cursor.execute(
            f'CREATE UNIQUE INDEX "unique_legacy_b_{suffix}" ON "{table}" (tag_id) WHERE legacy_b_id IS NOT NULL'
        )
        cursor.execute(f'CREATE UNIQUE INDEX "unique_keeper_{suffix}" ON "{table}" (tag_id, keeper_id)')
        cursor.execute(f'CREATE INDEX "{table}_legacy_a_id_idx" ON "{table}" (legacy_a_id)')
    try:
        yield table, suffix
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
            cursor.execute(f'DROP TABLE IF EXISTS "{parent}" CASCADE')


def _apply(op):
    with connection.schema_editor(atomic=False) as schema_editor:
        op.database_forwards("posthog", schema_editor, from_state=None, to_state=None)


def _rules(table):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT con.conname FROM pg_constraint con JOIN pg_class t ON t.oid = con.conrelid
            WHERE t.relname = %(table)s
            UNION
            SELECT i.relname FROM pg_index ix
            JOIN pg_class t ON t.oid = ix.indrelid JOIN pg_class i ON i.oid = ix.indexrelid
            WHERE t.relname = %(table)s
            """,
            {"table": table},
        )
        return {row[0] for row in cursor.fetchall()}


@pytest.mark.django_db
def test_drops_every_rule_on_the_retiring_columns_and_keeps_the_rest(temp_table):
    table, suffix = temp_table
    op = DropColumnConstraints(table, columns=["legacy_a_id", "legacy_b_id"])

    _apply(op)
    _apply(op)

    assert _rules(table) == {
        f"{table}_pkey",
        f"{table}_legacy_a_id_1c2d3e4f_fk",
        "keeper_positive",
        f"unique_keeper_{suffix}",
        f"{table}_legacy_a_id_idx",
    }


def test_needs_a_list_of_columns():
    with pytest.raises(ValueError, match="list of columns"):
        DropColumnConstraints("test_dropcc", columns="legacy_a_id")
