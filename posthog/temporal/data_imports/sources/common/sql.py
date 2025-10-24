from __future__ import annotations

import abc
import typing
import functools
import collections.abc

import pyarrow as pa


@typing.runtime_checkable
class Column(typing.Protocol):
    """Protocol for `SQLSource` columns.

    We choose to use a protocol as each source may express a column with
    different parameters. Ultimately, what matters to us is that a column can be
    expressed as a `pyarrow.Field`. When implementing this protocol, populate
    your object with any attributes required to accurately resolve a
    `pyarrow.Field`.
    """

    name: str

    def __repr__(self):
        return f"<{self.__class__.__name__}: '{self.name}'>"

    @abc.abstractmethod
    def to_arrow_field(self) -> pa.Field[pa.DataType]: ...


class TableBase:
    """Base class for `TableReference` and `Table`."""

    type: typing.Literal["table", "view", "materialized_view"] | None

    def __init__(
        self,
        name: str,
        parents: tuple[str, ...] | None = None,
        alias: str | None = None,
        type: typing.Literal["table", "view", "materialized_view"] | None = None,
    ) -> None:
        self.name = name
        self.parents = parents
        self.alias = alias
        self.type = type

    def __repr__(self):
        return f"<{self.__class__.__name__}: '{self.fully_qualified_name}'>"

    @property
    def fully_qualified_name(self) -> str:
        """Return this table's fully qualified name.

        This consists of the parents and name concatenated, separated by a ".".
        """
        if self.parents:
            return f'{".".join(self.parents)}.{self.name}'
        else:
            return self.name


class TableReference(TableBase):
    """A reference to a `Table` from a `SQLSource`.

    This class exists because there is a need to represent a table before we
    have had a chance to query a `SQLSource`. In other words, the table
    referenced by a `TableReference` may or may not exist, and should be checked
    with the `SQLSource`.
    """

    # TODO: The `SQLSource` interface is still in progress, but it will offer a
    # `get_table` method that takes a `TableReference and returns a `Table`

    @classmethod
    def from_fully_qualified_name(
        cls: type[typing.Self], fully_qualified_name: str, *, separator: str = "."
    ) -> typing.Self:
        """Initialize a `TableReference` from a fully qualified name.

        A fully qualified name is a string of dot separated names. Only the last
        name is required, all parents can be omitted.
        """
        try:
            all_parents, name = fully_qualified_name.rsplit(sep=separator, maxsplit=1)
        except ValueError:
            name = fully_qualified_name
            parents = None
        else:
            parents = tuple(parent for parent in all_parents.split("."))

        return cls(name=name, parents=parents)


ColumnType = typing.TypeVar("ColumnType", bound=Column)


class Table(TableBase, typing.Generic[ColumnType]):
    """A table obtained from a `SQLSource`.

    A table may be better understood as a container of `Column`, so indexing,
    iteration, length checks, and membership tests are supported.
    """

    def __init__(
        self,
        name: str,
        columns: list[ColumnType],
        parents: tuple[str, ...] | None = None,
        alias: str | None = None,
        type: typing.Literal["table", "view", "materialized_view"] | None = None,
    ) -> None:
        super().__init__(name, parents, alias, type)
        self.columns = columns

    def __iter__(self) -> collections.abc.Iterator[ColumnType]:
        """Iterate through this `Table`'s columns."""
        yield from self.columns

    def __len__(self) -> int:
        """Return the number of columns in this `Table`."""
        return len(self.columns)

    def __getitem__(self, key: int | str) -> ColumnType:
        """Get a column from this `Table`.

        Raises:
            TypeError: On an unsupported key type.
            KeyError: If a `str` key doesn't exist.
            IndexError: If an `int` key is out of bounds.
        """
        if isinstance(key, int):
            return self.columns[key]
        elif isinstance(key, str):
            return self._get_column_by_name(key)

        raise TypeError(f"unsupported key type: '{type(key)}'")

    def __contains__(self, column: ColumnType | str) -> bool:
        """Check if this `Table` contains a column.

        Accepts both an object that implements `Column` and a `str`. The latter
        case being interpreted as the name of the column.
        """
        if not self.columns:
            return False

        if isinstance(column, str):
            try:
                _ = self._get_column_by_name(column)
            except KeyError:
                return False
            else:
                return True
        else:
            return column in self.columns

    @functools.lru_cache
    def _get_column_by_name(self, key: str) -> ColumnType:
        """Get a column from this `Table` by its name.

        Raises:
            KeyError: If a column with the name doesn't exist.
        """
        try:
            return next(column for column in self.columns if column.name == key)
        except StopIteration:
            raise KeyError(key)

    def to_arrow_schema(self) -> pa.Schema:
        """Generate a `pyarrow.Schema` that matches this `Table`'s columns."""
        return pa.schema(column.to_arrow_field() for column in self.columns)


TableSchemas = dict[str, Table[ColumnType]]
