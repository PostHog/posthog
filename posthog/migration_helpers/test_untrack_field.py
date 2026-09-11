"""Tests for the untrack_field helper.

The database_operations pass-through is the one that carries weight: a DropForeignKey that
never reaches the migration leaves behind the orphaned constraint this helper exists to clear.
"""

import pytest

from django.db import migrations

from posthog.migration_helpers import DropForeignKey, untrack_field


def test_every_field_leaves_model_state():
    operation = untrack_field("mymodel", "owner", "other")

    assert isinstance(operation, migrations.SeparateDatabaseAndState)
    removals = [op for op in operation.state_operations if isinstance(op, migrations.RemoveField)]

    assert len(removals) == len(operation.state_operations)
    assert [(op.model_name, op.name) for op in removals] == [
        ("mymodel", "owner"),
        ("mymodel", "other"),
    ]


def test_the_database_operations_reach_the_migration():
    drop = DropForeignKey("posthog_mymodel", column="owner_id")

    operation = untrack_field("mymodel", "owner", database_operations=[drop])

    assert operation.database_operations == [drop]


def test_the_column_stays_when_nothing_is_passed():
    operation = untrack_field("mymodel", "owner")

    assert operation.database_operations == []


def test_no_field_names_is_refused():
    with pytest.raises(ValueError, match="at least one field name"):
        untrack_field("mymodel")
