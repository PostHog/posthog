from __future__ import annotations

import pytest

import pyarrow as pa

from posthog.temporal.data_imports.sources.common.sql import (
    Column,
    Table,
    TableReference,
    normalize_cursor_column_names,
    normalize_schema_field_names,
)


class SimpleColumn(Column):
    """Simple test column."""

    def __init__(self, name: str) -> None:
        self.name = name

    def to_arrow_field(self) -> pa.Field[pa.DataType]:
        return pa.field(self.name, pa.string(), nullable=True)


def test_table_get_item():
    """Test `Table.__getitem__` with `int` and `str` keys."""
    column_name = "some_column"
    column = SimpleColumn(column_name)
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
    column = SimpleColumn(column_name)
    table = Table(name="test", columns=[column])

    assert column_name in table
    assert "not a column" not in table


def test_table_len():
    """Test `Table.__len__` returns number of columns."""
    column_name = "some_column"
    column = SimpleColumn(column_name)
    table = Table(name="test", columns=[column])

    assert len(table) == 1

    table = Table(name="test", columns=[column, column, column])

    assert len(table) == 3


def test_table_to_arrow_schema():
    """Test `to_arrow_schema` method returns fields based on columns."""
    column_name = "some_column"
    column_0 = SimpleColumn(column_name)
    column_1 = SimpleColumn(column_name)
    column_2 = SimpleColumn(column_name)
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
    column = SimpleColumn(column_name)
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


@pytest.mark.parametrize(
    "raw_name,expected",
    [
        ("already_snake_case", "already_snake_case"),
        ("FamilyName GivenName", "family_name_given_name"),
        ("FamilyName Space GivenName", "family_name_space_given_name"),
        ("Customer ID", "customer_id"),
        ("column-with-dashes", "column_with_dashes"),
        ("MixedCASEName", "mixed_case_name"),
    ],
)
def test_normalize_schema_field_names(raw_name, expected):
    schema = pa.schema(
        [
            pa.field(raw_name, pa.int64(), nullable=True),
            pa.field("id", pa.int32(), nullable=False),
        ]
    )

    normalized = normalize_schema_field_names(schema)

    assert normalized.names == [expected, "id"]
    # Type and nullability are preserved.
    assert normalized.field(0).type == pa.int64()
    assert normalized.field(0).nullable is True
    assert normalized.field(1).nullable is False


def test_normalize_cursor_column_names_handles_both_driver_shapes():
    # pymysql / pymssql: description entries are tuples, name is column[0].
    tuple_description = [("FamilyName GivenName",), ("id",)]
    assert normalize_cursor_column_names(tuple_description) == ["family_name_given_name", "id"]

    # psycopg: description entries have a `.name` attribute.
    class _DescribedColumn:
        def __init__(self, name: str) -> None:
            self.name = name

    psycopg_description = [_DescribedColumn("FamilyName GivenName"), _DescribedColumn("id")]
    assert normalize_cursor_column_names(psycopg_description) == ["family_name_given_name", "id"]


@pytest.mark.parametrize("empty", [None, []])
def test_normalize_cursor_column_names_empty(empty):
    assert normalize_cursor_column_names(empty) == []


def test_schema_and_dict_keys_align_after_normalization():
    """End-to-end guard: a raw MySQL-style schema paired with a raw cursor.description
    should land on matching keys in the pa.Table that `table_from_iterator` builds.

    Regression test for issue 019da925-d07f-7c42 where the arrow schema carried the
    normalized name (`family_name_given_name`) but the per-row dict kept the raw
    driver name (`FamilyName GivenName`), causing `pa.Table.from_pydict` to fail with
    KeyError.
    """
    raw_schema = pa.schema(
        [
            pa.field("FamilyName GivenName", pa.int64(), nullable=True),
            pa.field("FamilyName Space GivenName", pa.int64(), nullable=True),
            pa.field("id", pa.int32(), nullable=False),
        ]
    )
    raw_description = [("FamilyName GivenName",), ("FamilyName Space GivenName",), ("id",)]

    arrow_schema = normalize_schema_field_names(raw_schema)
    column_names = normalize_cursor_column_names(raw_description)

    rows = [(1, 10, 100), (2, 20, 200)]
    dicts = [dict(zip(column_names, row)) for row in rows]
    columnar = {k: pa.array([d[k] for d in dicts]) for k in dicts[0]}

    table = pa.Table.from_pydict(columnar, schema=arrow_schema)
    assert table.column_names == ["family_name_given_name", "family_name_space_given_name", "id"]
    assert table.num_rows == 2
