"""Functional tests for SafeDropTable.

Each test builds a real child/parent pair with real Django-shaped foreign keys, so the
catalog lookup that decides the lock list runs against the same pg_constraint rows a
migration would see.
"""

import re
import uuid

import pytest

from django.db import connection

from posthog.migration_helpers import SafeDropTable


@pytest.fixture
def temp_tables():
    suffix = uuid.uuid4().hex[:8]
    parent = f"test_safedrop_parent_{suffix}"
    child_a = f"test_safedrop_child_a_{suffix}"
    child_b = f"test_safedrop_child_b_{suffix}"
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE TABLE "{parent}" (id serial primary key)')
        for child in (child_a, child_b):
            cursor.execute(
                f"""
                CREATE TABLE "{child}" (
                    id serial primary key,
                    owner_id int REFERENCES "{parent}"(id) DEFERRABLE INITIALLY DEFERRED
                )
                """
            )
    try:
        yield child_a, child_b, parent
    finally:
        with connection.cursor() as cursor:
            for table in (child_a, child_b, parent):
                cursor.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')


def _apply(op, collect=False):
    schema_editor = connection.schema_editor(atomic=False, collect_sql=collect)
    schema_editor.__enter__()
    try:
        op.database_forwards("posthog", schema_editor, from_state=None, to_state=None)
    finally:
        schema_editor.__exit__(None, None, None)
    return schema_editor.collected_sql if collect else None


def _tables_exist(*tables):
    with connection.cursor() as cursor:
        cursor.execute("SELECT relname FROM pg_class WHERE relname = ANY(%s) AND relkind = 'r'", [list(tables)])
        return {row[0] for row in cursor.fetchall()}


@pytest.mark.django_db
def test_locks_the_referenced_parent_before_dropping(temp_tables):
    # The deadlock this helper exists to stop comes from the parent lock DROP TABLE takes
    # part-way through the statement. Locking only the dropped tables would bring it back.
    child_a, child_b, parent = temp_tables

    collected = _apply(collect=True, op=SafeDropTable(child_a, child_b))

    lock = next(statement for statement in collected if "LOCK TABLE" in statement)
    drop = next(statement for statement in collected if "DROP TABLE" in statement)
    assert collected.index(lock) < collected.index(drop)
    for table in (child_a, child_b, parent):
        assert table in lock


@pytest.mark.django_db
def test_the_lock_phase_gives_up_before_any_deadlock_detector_runs(temp_tables):
    # A waiting backend runs the deadlock detector after deadlock_timeout, and the backend
    # that finds the cycle is the one Postgres kills. The migration has to abandon its wait
    # first, or the application query waiting on it is killed instead.
    child_a, _, _ = temp_tables
    with connection.cursor() as cursor:
        cursor.execute("SELECT setting::int FROM pg_settings WHERE name = 'deadlock_timeout'")
        deadlock_ms = cursor.fetchone()[0]

    collected = _apply(collect=True, op=SafeDropTable(child_a))

    budgets = [int(match) for match in re.findall(r"SET LOCAL \w+_timeout = '(\d+)ms'", "\n".join(collected))]
    assert len(budgets) == 2  # lock_timeout bounds one attempt, statement_timeout bounds them all
    assert all(0 < budget < deadlock_ms for budget in budgets)


@pytest.mark.django_db
def test_drops_every_named_table(temp_tables):
    child_a, child_b, parent = temp_tables

    _apply(SafeDropTable(child_a, child_b))

    assert _tables_exist(child_a, child_b, parent) == {parent}


@pytest.mark.django_db
def test_a_second_run_is_a_no_op(temp_tables):
    child_a, child_b, _ = temp_tables
    op = SafeDropTable(child_a, child_b)

    _apply(op)
    _apply(op)

    assert _tables_exist(child_a, child_b) == set()


def test_the_drop_cannot_be_reversed():
    op = SafeDropTable("test_safedrop_child")

    # Migration.unapply checks the flag first and never reaches database_backwards, so the
    # top-level path needs its own assertion.
    assert op.reversible is False
    with pytest.raises(NotImplementedError, match="irreversible"):
        op.database_backwards("posthog", None, None, None)


def test_needs_a_table():
    with pytest.raises(ValueError, match="at least one table"):
        SafeDropTable()
