import collections
from collections.abc import Sequence


class ConflictingColumnNamesError(Exception):
    pass


def validate_unique_column_names(column_names: Sequence[str]) -> None:
    """Reject result column names a view's stored schema cannot represent.

    When two select items share a result name, ClickHouse keeps the qualified dotted name
    (``table.column``) for the unaliased one, so counting by the bare last segment catches
    both plain duplicates and the collision-qualified form.
    """
    bare_name_counts = collections.Counter(name.rsplit(".", 1)[-1] for name in column_names)
    duplicates = sorted({name for name, count in bare_name_counts.items() if count > 1})
    if not duplicates:
        return

    quoted = ", ".join(f"'{name}'" for name in duplicates)
    raise ConflictingColumnNamesError(
        f"The query returns more than one column named {quoted}. Give each column a unique alias."
    )


def validate_materializable_column_names(column_names: Sequence[str]) -> None:
    """Reject result column names a materialized table cannot represent.

    Stricter than :func:`validate_unique_column_names`: materialization references columns
    by name when it rewraps the query to cast types for Arrow, and a dotted name resolves
    as a single identifier there rather than as ``table.column``.
    """
    validate_unique_column_names(column_names)

    dotted = sorted(name for name in column_names if "." in name)
    if not dotted:
        return

    quoted = ", ".join(f"'{name}'" for name in dotted)
    raise ConflictingColumnNamesError(f"Column names cannot contain dots. Give {quoted} an alias without a dot.")
