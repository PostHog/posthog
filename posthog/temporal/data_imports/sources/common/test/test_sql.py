from __future__ import annotations

import pytest

import pyarrow as pa

from posthog.temporal.data_imports.sources.common.sql import Column, Table, TableReference


class TestColumn(Column):
    """Simple test column."""

    def __init__(self, name: str) -> None:
        self.name = name

    def to_arrow_field(self) -> pa.Field[pa.DataType]:
        return pa.field(self.name, pa.string(), nullable=True)


def test_table_get_item():
    """Test `Table.__getitem__` with `int` and `str` keys."""
    column_name = "some_column"
    column = TestColumn(column_name)
    table = Table(name="test", columns=[column])

    assert table[0] == column
    assert table[column_name] == column

    with pytest.raises(KeyError):
        table["something"]

    with pytest.raises(IndexError):
        table[1000]

    with pytest.raises(TypeError):
        table[object]  # type: ignore


def test_table_contains():
    """Test `Table.__contains__` returns `True` with existing column."""
    column_name = "some_column"
    column = TestColumn(column_name)
    table = Table(name="test", columns=[column])

    assert column_name in table
    assert "not a column" not in table


def test_table_len():
    """Test `Table.__len__` returns number of columns."""
    column_name = "some_column"
    column = TestColumn(column_name)
    table = Table(name="test", columns=[column])

    assert len(table) == 1

    table = Table(name="test", columns=[column, column, column])

    assert len(table) == 3


def test_table_to_arrow_schema():
    """Test `to_arrow_schema` method returns fields based on columns."""
    column_name = "some_column"
    column_0 = TestColumn(column_name)
    column_1 = TestColumn(column_name)
    column_2 = TestColumn(column_name)
    table = Table(name="test", columns=[column_0])
    schema = table.to_arrow_schema()

    assert len(schema) == 1
    assert schema.field(0) == column_0.to_arrow_field()

    table = Table(name="test", columns=[column_0, column_1, column_2])
    schema = table.to_arrow_schema()

    assert len(schema) == 3
    assert schema.field(0) == column_0.to_arrow_field()
    assert schema.field(1) == column_1.to_arrow_field()
    assert schema.field(2) == column_2.to_arrow_field()


def test_table_fully_qualified_name():
    """Test `Table` generates correct fully qualified names."""
    column_name = "some_column"
    column = TestColumn(column_name)
    table = Table(name="test", columns=[column])

    assert table.fully_qualified_name == "test"

    table = Table(name="test", columns=[column], parents=("database", "schema"))

    assert table.fully_qualified_name == "database.schema.test"


def test_table_reference_from_fully_qualified_name():
    """Test initializing a `TableReference` from a fully qualified name."""

    table_ref = TableReference.from_fully_qualified_name("database.schema.test")
    assert table_ref.fully_qualified_name == "database.schema.test"
    assert table_ref.name == "test"
    assert table_ref.parents == ("database", "schema")
