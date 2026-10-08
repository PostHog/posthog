"""Functional tests for DropForeignKey.

Each test builds a real parent/child pair with real Django-shaped foreign keys, so the
catalog lookup runs against the same pg_constraint rows a migration would see.
"""

import time
import uuid

import pytest

from django.db import connection, connections
from django.db.utils import OperationalError

from posthog.migration_helpers import DropForeignKey
from posthog.migration_helpers.lock_phase import MAX_LOCK_BUDGET_MS


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


def _apply(op, collect=False):
    schema_editor = connection.schema_editor(atomic=False, collect_sql=collect)
    schema_editor.__enter__()
    try:
        op.database_forwards("posthog", schema_editor, from_state=None, to_state=None)
    finally:
        schema_editor.__exit__(None, None, None)
    return schema_editor.collected_sql if collect else None


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


@pytest.mark.parametrize(
    "column, remaining",
    [
        ("owner_id", {"other_id"}),
        (["owner_id", "other_id"], set()),
    ],
)
@pytest.mark.django_db
def test_drops_only_the_named_columns(temp_tables, column, remaining):
    child, _, _ = temp_tables

    _apply(DropForeignKey(child, column=column))

    assert _fk_columns(child) == remaining


@pytest.mark.django_db
def test_locks_every_parent_before_the_child_and_before_any_drop(temp_tables):
    # DROP CONSTRAINT on its own locks the child first and each parent after it, which is
    # the order that crosses a live read joining parent to child and deadlocks.
    child, parent_a, parent_b = temp_tables

    collected = _apply(collect=True, op=DropForeignKey(child, column=["owner_id", "other_id"]))

    lock = next(statement for statement in collected if "LOCK TABLE" in statement)
    first_drop = next(statement for statement in collected if "DROP CONSTRAINT" in statement)
    assert collected.index(lock) < collected.index(first_drop)
    assert lock.index(parent_a) < lock.index(child)
    assert lock.index(parent_b) < lock.index(child)


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


# The raised value is the one an operator sets on a loaded server. Half of it is a ten second
# wait, which the op's own ceiling has to cut back.
@pytest.mark.parametrize("server_deadlock_timeout", [None, "20s"])
@pytest.mark.django_db(transaction=True)
def test_a_contended_parent_fails_fast(temp_tables, server_deadlock_timeout):
    child, parent_a, _ = temp_tables
    blocker = connections.create_connection("default")
    blocker.set_autocommit(False)
    with connection.cursor() as cursor:
        if server_deadlock_timeout is not None:
            cursor.execute(f"SET deadlock_timeout = '{server_deadlock_timeout}'")
        cursor.execute("SELECT setting::int FROM pg_settings WHERE name = 'deadlock_timeout'")
        deadlock_seconds = cursor.fetchone()[0] / 1000
        # Far longer than the op allows itself, so an unbounded drop stalls this test the way
        # it stalls a deploy instead of failing it.
        cursor.execute("SET lock_timeout = '10s'")
    try:
        with blocker.cursor() as cursor:
            # An open read holds ACCESS SHARE on the parent, which the drop's ACCESS
            # EXCLUSIVE has to wait for.
            cursor.execute(f'SELECT count(*) FROM "{parent_a}"')

        started = time.monotonic()
        # The lock phase arms lock_timeout and statement_timeout with the same budget, so
        # either one can be the one that fires.
        with pytest.raises(OperationalError, match="lock timeout|statement timeout"):
            _apply(DropForeignKey(child, column="owner_id"))
        waited = time.monotonic() - started
    finally:
        blocker.rollback()
        blocker.close()
        with connection.cursor() as cursor:
            cursor.execute("RESET lock_timeout")
            cursor.execute("RESET deadlock_timeout")

    # Under deadlock_timeout, so the op abandons the wait before its own deadlock detector
    # runs. Under the ceiling too, so a server that allows a longer wait does not get one.
    assert waited < deadlock_seconds
    assert waited < MAX_LOCK_BUDGET_MS / 1000 + 1
    assert _fk_columns(child) == {"owner_id", "other_id"}
