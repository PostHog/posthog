import abc
import typing
import datetime as dt
import functools
import collections
import collections.abc

import pyarrow as pa

from products.batch_exports.backend.temporal.utils import JsonType

_T = typing.TypeVar("_T")

EPOCH = dt.datetime(1970, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
EPOCH_SECONDS = pa.scalar(EPOCH, type=pa.timestamp("s", tz="UTC"))
EPOCH_MILLISECONDS = pa.scalar(EPOCH, type=pa.timestamp("ms", tz="UTC"))
EPOCH_MICROSECONDS = pa.scalar(EPOCH, type=pa.timestamp("us", tz="UTC"))


def _noop_cast(arr: pa.Array) -> pa.Array:
    return arr


def _make_ensure_array(
    func: collections.abc.Callable[[pa.Array], pa.Array | pa.Scalar],
) -> collections.abc.Callable[[pa.Array], pa.Array]:
    """Wrap `func` with an assertion that returned value is an `pyarrow.Array`.

    `pyarrow.compute` functions usually return either array values or scalar values.
    However, we work exclusively with arrays and thus can expect that if we pass an
    array we'll get one back. But `pyarrow.compute` functions are not properly
    type-hinted to represent this.

    So, to help mypy understand this, we decorate `func` with an assertion to confirm we
    got an `pyarrow.Array` back.

    Naturally, this comes with the implicit, hereby made explicit, request that you
    review the pyarrow documentation to confirm that the used `pyarrow.compute` function
    actually returns an `pyarrow.Array` when passed one as input. Most of the time, this
    is the case, but I have not reviewed all of them, and new ones may be added over
    time.
    """

    @functools.wraps(func)
    def f(arr: pa.Array) -> pa.Array:
        result = func(arr)
        assert isinstance(result, pa.Array)
        return result

    return f


TypeTupleToCastMapping = dict[tuple[pa.DataType, pa.DataType], collections.abc.Callable[[pa.Array], pa.Array]]

# I played around with the idea of making this a proper graph and then using DFS/BFS to
# find a path between two types. But that seemed too much complexity for our current
# requirements, so I tabled the idea for the time being. Leaving a comment here in case
# the higher complexity is warranted in the future.
COMPATIBLE_TYPES: TypeTupleToCastMapping = {
    (pa.timestamp("s", tz="UTC"), pa.int64()): _make_ensure_array(
        functools.partial(pa.compute.seconds_between, EPOCH_SECONDS)
    ),
    (pa.timestamp("ms", tz="UTC"), pa.int64()): _make_ensure_array(
        functools.partial(pa.compute.milliseconds_between, EPOCH_MILLISECONDS)
    ),
    (pa.timestamp("us", tz="UTC"), pa.int64()): _make_ensure_array(
        functools.partial(pa.compute.microseconds_between, EPOCH_MICROSECONDS)
    ),
    (pa.string(), JsonType()): _make_ensure_array(functools.partial(pa.compute.cast, target_type=JsonType())),
}


def are_types_compatible(
    source: pa.DataType,
    target: pa.DataType,
    extra_compatible_types: TypeTupleToCastMapping | None = None,
) -> tuple[bool, collections.abc.Callable[[pa.Array], pa.Array] | None]:
    """Define whether a pair of Arrow data types are compatible.

    Compatible means we can cast source to target without or with an acceptably low loss
    of precision.

    These rules can be destination-dependent, so the `extra_compatible_types` argument
    can be used to pass new compatible types or overwrite existing ones.

    Arguments:
        source: Arrow data type we want to cast from.
        target: Arrow data type we want to cast to.
        extra_compatible_types: Additional casting rules.

    Returns:
        A tuple in which the first element is whether source can be casted to target,
        and the second element is a casting function when the first element is `True`,
        otherwise `None`.
    """
    if source == target:
        # Callers should be checking this, but just in case...
        return (True, _noop_cast)

    compatible_mapping = {**COMPATIBLE_TYPES, **(extra_compatible_types or {})}
    try:
        return (True, compatible_mapping[(source, target)])
    except KeyError:
        return (False, None)


class Field[T](typing.Protocol):
    """A protocol for a field in a batch exports destination.

    A `Field`'s responsibility is to handle resolution between a `pyarrow.Field` and
    a destination-specific field, by converting to and from each one.

    Flexibility inherent to the usage of a protocol instead of a class and with the
    usage of a generic `T` destination field is intended to allow implementations
    of this protocol with enough margin to handle any specific types from all
    destinations.
    """

    name: str
    data_type: pa.DataType

    @classmethod
    def from_arrow_field(cls, field: pa.Field) -> typing.Self: ...

    def to_arrow_field(cls) -> pa.Field: ...

    @classmethod
    def from_destination_field(cls, field: T) -> typing.Self: ...

    def to_destination_field(cls) -> T: ...

    def with_new_arrow_type(self, new_type: pa.DataType) -> "Field[T]": ...

    def __repr__(self) -> str:
        return f"<Field '{self.name}': data_type={self.data_type}>"

    def __str__(self) -> str:
        return self.name

    def __hash__(self) -> int:
        return self.name.__hash__()


FieldType = typing.TypeVar("FieldType", bound=Field)


class TableBase:
    """Base class for `TableReference` and `Table`."""

    def __init__(
        self,
        name: str,
        parents: collections.abc.Iterable[str] = (),
    ) -> None:
        self.name = name
        self.parents = tuple(parents)

    def __repr__(self):
        return f"<{self.__class__.__name__}: '{self.fully_qualified_name}'>"

    def __str__(self) -> str:
        return self.fully_qualified_name

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
    """A reference to a `Table` by its fully qualified name."""

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
            parents = (parent for parent in all_parents.split("."))

        return cls(name=name, parents=parents or ())


class Table(TableBase, typing.Generic[FieldType]):
    """A Table abstraction for batch exports.

    The intended use is to wrap the actual target table used in a destination with a
    common API for all batch exports to use.

    Moreover, this can also be derived from an arrow schema, to allow comparisons with
    tables derived from destination data.
    """

    def __init__(
        self,
        name: str,
        fields: collections.abc.Iterable[FieldType],
        parents: collections.abc.Iterable[str] = (),
        primary_key: collections.abc.Iterable[str] = (),
        version_key: collections.abc.Iterable[str] = (),
    ) -> None:
        super().__init__(name, parents)
        self._primary_key = tuple(primary_key)
        self._version_key = tuple(version_key)
        self.fields: list[FieldType] = list(fields)

    @classmethod
    @abc.abstractmethod
    def from_arrow_schema(cls, schema: pa.Schema, **kwargs) -> typing.Self:
        """Sub-classes should implement how to create a Table from an arrow schema.

        The body of this method should just be a call to from_arrow_schema_full.

        This method offers a relaxed signature via kwargs to allow sub-classes some
        flexibility in figuring out how to:
        * Pass their concrete Field implementation as field_type.
            * Unfortunately, generic types are not available at runtime, so we need this
              to be passed as an argument, even if the class definition already displays
              the concrete Field type.
        * Obtain name and parents.
        """
        raise NotImplementedError()

    @classmethod
    def from_arrow_schema_full(
        cls,
        schema: pa.Schema,
        field_type: type[FieldType],
        name: str,
        parents: collections.abc.Iterable[str] = (),
        primary_key: collections.abc.Iterable[str] = (),
        version_key: collections.abc.Iterable[str] = (),
    ) -> typing.Self:
        return cls(
            name=name,
            fields=(field_type.from_arrow_field(field) for field in schema),
            parents=parents,
            primary_key=primary_key,
            version_key=version_key,
        )

    @property
    def primary_key(self) -> tuple[str, ...]:
        """A non-empty set of field names representing the primary key for this table.

        This is required for the table to be considered mutable as the primary key is
        used to match new rows with existing rows.
        """
        return self._primary_key

    @primary_key.setter
    def primary_key(self, value: collections.abc.Iterable[str]) -> None:
        primary_key = tuple(value)

        self._contains_fields(primary_key, raise_if_missing=True)

        self._primary_key = primary_key

    @property
    def version_key(self) -> tuple[str, ...]:
        """A non-empty set of field names representing the version key for this table.

        This is required for the table to be considered mutable as the version key is
        used to decide whether a matching row needs to be updated or not.
        """
        return self._version_key

    @version_key.setter
    def version_key(self, value: collections.abc.Iterable[str]) -> None:
        version_key = tuple(value)

        self._contains_fields(version_key, raise_if_missing=True)

        self._version_key = version_key

    def _contains_fields(self, field_names: collections.abc.Iterable[str], *, raise_if_missing: bool = False) -> bool:
        """Check if this table contains `field_names`."""
        missing = tuple(name for name in field_names if name not in self)

        if not missing:
            return True

        if raise_if_missing:
            if len(missing) == 1:
                raise ValueError(f"Field is not in this table: '{missing[0]}'")
            else:
                raise ValueError(f"Fields are not in this table: '{", ".join(missing)}'")

        return False

    def __iter__(self) -> collections.abc.Iterator[FieldType]:
        """Iterate through this `Table`'s fields."""
        yield from self.fields

    def __reversed__(self) -> collections.abc.Iterator[FieldType]:
        """Iterate through this `Table`'s fields in reverse order."""
        yield from reversed(self.fields)

    def __len__(self) -> int:
        """Return the number of fields in this `Table`."""
        return len(self.fields)

    def __getitem__(self, key: int | str) -> FieldType:
        """Get a field from this `Table`.

        Raises:
            TypeError: On an unsupported key type.
            KeyError: If a `str` key doesn't exist.
            IndexError: If an `int` key is out of bounds.
        """
        if isinstance(key, int):
            return self.fields[key]
        elif isinstance(key, str):
            return self._get_field_by_name(key)

        raise TypeError(f"unsupported key type: '{type(key)}'")

    def __setitem__(self, key: int | str, value: FieldType) -> None:
        """Set a field in this `Table`.

        Raises:
            TypeError: On an unsupported key type.
            IndexError: If an `int` key is out of bounds.
        """
        if isinstance(key, int):
            self.fields[key] = value

        elif isinstance(key, str):
            if not key == value.name:
                raise ValueError(f"Cannot update '{key}' with field of name '{value.name}'")

            try:
                existing = self._get_field_by_name(key)
                index = self.fields.index(existing)
            except KeyError:
                # New field.
                self.fields.append(value)
            else:
                self.fields[index] = value

        else:
            raise TypeError(f"unsupported key type: '{type(key)}'")

        self._get_field_by_name.cache_clear()

    def __delitem__(self, key: int | str) -> None:
        """Delete a field from this `Table`.

        Raises:
            TypeError: On an unsupported key type.
            KeyError: If a `str` key doesn't exist.
            IndexError: If an `int` key is out of bounds.
        """
        if isinstance(key, int):
            del self.fields[key]

        elif isinstance(key, str):
            existing = self._get_field_by_name(key)
            index = self.fields.index(existing)

            del self.fields[index]

        self._get_field_by_name.cache_clear()

    def __contains__(self, field: FieldType | str) -> bool:
        """Check if this `Table` contains a field.

        Accepts both an object that implements `Field` and a `str`. The latter
        case being interpreted as the name of the field.
        """
        if not self.fields:
            return False

        if isinstance(field, str):
            try:
                _ = self._get_field_by_name(field)
            except KeyError:
                return False
            else:
                return True
        else:
            return field in self.fields

    @functools.lru_cache
    def _get_field_by_name(self, key: str) -> FieldType:
        """Get a field from this `Table` by its name.

        This method uses a LRU cache to avoid iterating more than once per `key`, in case
        it is in a loop and frequently getting fields by name.

        Raises:
            KeyError: If a field with the name doesn't exist.
        """
        try:
            return next(field for field in self.fields if field.name == key)
        except StopIteration:
            raise KeyError(key)

    def is_mutable(self) -> bool:
        return len(self.primary_key) > 0 and len(self.version_key) > 0
