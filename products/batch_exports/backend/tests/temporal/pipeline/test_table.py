import typing
import datetime as dt

import pytest

import pyarrow as pa

from products.batch_exports.backend.temporal.pipeline.table import (
    Field,
    Table,
    TableBase,
    TableReference,
    are_types_compatible,
)
from products.batch_exports.backend.temporal.utils import JsonType


@pytest.mark.parametrize(
    "source,target,expected_compatible,value,expected_result",
    (
        (
            pa.timestamp("s", tz="UTC"),
            pa.int64(),
            True,
            pa.array(
                [dt.datetime(2025, 1, 1, tzinfo=dt.UTC), dt.datetime(2025, 1, 2, tzinfo=dt.UTC)],
                type=pa.timestamp("s", tz="UTC"),
            ),
            pa.array(
                [
                    dt.datetime(2025, 1, 1, tzinfo=dt.UTC).timestamp(),
                    dt.datetime(2025, 1, 2, tzinfo=dt.UTC).timestamp(),
                ],
                type=pa.int64(),
            ),
        ),
        (
            pa.string(),
            JsonType(),
            True,
            pa.array(["{1: 1}", "{2: 2}"], type=pa.string()),
            pa.array(
                ["{1: 1}", "{2: 2}"],
                type=JsonType(),
            ),
        ),
        (
            pa.int32(),
            pa.int16(),
            False,
            None,
            None,
        ),
    ),
)
def test_are_types_compatible(
    source: pa.DataType,
    target: pa.DataType,
    expected_compatible: bool,
    value: pa.Array | None,
    expected_result: pa.Array | None,
):
    compatible, cast_func = are_types_compatible(source, target)

    assert compatible == expected_compatible

    if not compatible:
        assert cast_func is None

        return

    assert cast_func is not None
    assert value is not None

    result = cast_func(value)

    assert result == expected_result


@pytest.mark.parametrize(
    "name,parents,expected_fully_qualified_name",
    (
        ("test", ("parent",), "parent.test"),
        ("test", ("grandparent", "parent"), "grandparent.parent.test"),
        ("test", (), "test"),
    ),
)
def test_table_base_fully_qualified_name(name: str, parents: tuple[str, ...], expected_fully_qualified_name: str):
    t = TableBase(name, parents)
    assert t.fully_qualified_name == expected_fully_qualified_name == str(t)


def test_table_is_a_sequence_of_fields():
    """Test `Table` acts like a mutable sequence of `Field`s.

    Although not explicitly inheriting from the `MutableSequence` abc, we still provide
    all of its dunder methods, and thus we test them.
    """

    class TestField(Field):
        def __init__(self, name: str, data_type: pa.DataType):
            self.name = name
            self.data_type = data_type

        @classmethod
        def from_arrow_field(cls, field: pa.Field) -> typing.Self:
            raise NotImplementedError()

        def to_arrow_field(cls) -> pa.Field:
            raise NotImplementedError()

        @classmethod
        def from_destination_field(cls, field: typing.Any) -> typing.Self:
            raise NotImplementedError()

        def to_destination_field(cls) -> typing.Any:
            raise NotImplementedError()

        def with_new_arrow_type(self, new_type: pa.DataType) -> "TestField":
            raise NotImplementedError()

    class TestTable(Table):
        @classmethod
        def from_arrow_schema(cls, schema: pa.Schema, **kwargs) -> typing.Self:
            return cls(name="test", fields=[])

    one = TestField(name="one", data_type=pa.string())
    two = TestField(name="two", data_type=pa.string())
    t = TestTable(
        "test",
        (
            one,
            two,
        ),
    )

    # __len__
    assert len(t) == 2

    # __getitem__
    assert t["one"] == t[0] == one
    assert t["two"] == t[1] == two

    # __contains__
    assert "one" in t
    assert "two" in t
    assert one in t
    assert two in t

    three = TestField(name="three", data_type=pa.string())

    assert "three" not in t
    assert three not in t

    # __setitem__
    t["three"] = three

    assert "three" in t
    assert three in t

    new_three = TestField(name="three", data_type=pa.int64())
    t["three"] = new_three

    assert t["three"] == t[2] == new_three

    t[2] = three

    assert t["three"] == t[2] == three

    with pytest.raises(ValueError):
        t["three"] = one

    # __iter__
    assert list(t) == [one, two, three]

    # __reversed__
    assert list(reversed(t)) == [three, two, one]

    # __delitem__
    del t["three"]

    assert "three" not in t
    assert three not in t

    del t[1]

    assert "two" not in t
    assert two not in t


@pytest.mark.parametrize(
    "fully_qualified_name,expected_name,expected_parents,",
    (
        ("parent.test", "test", ("parent",)),
        ("grandparent.parent.test", "test", ("grandparent", "parent")),
        ("test", "test", ()),
    ),
)
def test_table_reference_from_fully_qualified_name(
    fully_qualified_name: str, expected_name: str, expected_parents: tuple[str, ...]
):
    t = TableReference.from_fully_qualified_name(fully_qualified_name)
    assert t.name == expected_name
    assert t.parents == expected_parents
