"""Functional tests for DropForeignKey.

Each test builds a real parent/child pair with real Django-shaped foreign keys, so the
catalog lookup runs against the same pg_constraint rows a migration would see.
"""

import uuid

import pytest

from django.db import connection

from posthog.migration_helpers import DropForeignKey


@pytest.fixture
def temp_tables():
    suffix = uuid.uuid4().hex[:8]
    parent_a = f"test_dropfk_parent_a_{suffix}"
    parent_b = f"test_dropfk_parent_b_{suffix}"
    child = f"test_dropfk_child_{suffix}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE TABLE "{parent_a}" (id serial primary key)')
        cursor.execute(f'CREATE TABLE "{parent_b}" (id serial primary key)')
        # Hash-suffixed names, the way Django writes them, so nothing here can be guessed.
        cursor.execute(
            f"""
            CREATE TABLE "{child}" (
                id serial primary key,
                owner_id int CONSTRAINT "{child}_owner_id_9a1bc3de_fk" REFERENCES "{parent_a}"(id)
                    DEFERRABLE INITIALLY DEFERRED,
                other_id int CONSTRAINT "{child}_other_id_4f2ea8b1_fk" REFERENCES "{parent_b}"(id)
                    DEFERRABLE INITIALLY DEFERRED
            )
            """
        )
    try:
        yield child, parent_a, parent_b
    finally:
        with connection.cursor() as cursor:
            for table in (child, parent_a, parent_b):
                cursor.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')


def _apply(op):
    schema_editor = connection.schema_editor(atomic=False)
    schema_editor.__enter__()
    try:
        op.database_forwards("posthog", schema_editor, from_state=None, to_state=None)
    finally:
        schema_editor.__exit__(None, None, None)


def _fk_columns(child):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT att.attname
            FROM pg_constraint con
            JOIN pg_class src ON src.oid = con.conrelid
            JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = ANY(con.conkey)
            WHERE con.contype = 'f' AND src.relname = %s
            """,
            [child],
        )
        return {row[0] for row in cursor.fetchall()}


@pytest.mark.django_db
def test_drops_only_the_named_column(temp_tables):
    child, _, _ = temp_tables

    _apply(DropForeignKey(child, column="owner_id"))

    assert _fk_columns(child) == {"other_id"}


@pytest.mark.django_db
def test_drops_only_the_named_parent(temp_tables):
    child, parent_a, _ = temp_tables

    _apply(DropForeignKey(child, to_table=parent_a))

    assert _fk_columns(child) == {"other_id"}


@pytest.mark.django_db
def test_a_second_run_is_a_no_op(temp_tables):
    child, _, _ = temp_tables
    op = DropForeignKey(child, column="owner_id")

    _apply(op)
    _apply(op)

    assert _fk_columns(child) == {"other_id"}


def test_the_drop_cannot_be_reversed():
    op = DropForeignKey("test_dropfk_child", column="owner_id")

    # Migration.unapply checks the flag first and never reaches database_backwards, so the
    # top-level path needs its own assertion.
    assert op.reversible is False
    with pytest.raises(NotImplementedError, match="AddForeignKeyNotValid"):
        op.database_backwards("posthog", None, None, None)


def test_needs_a_column_or_a_parent():
    with pytest.raises(ValueError, match="column, a to_table"):
        DropForeignKey("test_dropfk_child")
