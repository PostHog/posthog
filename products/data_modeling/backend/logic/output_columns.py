"""Checks on the column names a view's query outputs, shared by saving a view and materializing it."""

from collections.abc import Iterable


def duplicate_output_columns(names: Iterable[str]) -> list[str]:
    """Every spelling of each name the output repeats, in output order. Empty when all names are unique."""
    # Folded because Delta compares field names without case, so `userId` beside `userid` is as
    # unwritable as a literal repeat. Left to the write, that pair costs a full scan first.
    first_spelling: dict[str, str] = {}
    duplicates: list[str] = []
    seen_duplicates: set[str] = set()
    for name in names:
        folded = name.lower()
        if folded in first_spelling:
            for spelling in (first_spelling[folded], name):
                if spelling not in seen_duplicates:
                    seen_duplicates.add(spelling)
                    duplicates.append(spelling)
        else:
            first_spelling[folded] = name
    return duplicates


def duplicate_output_columns_message(duplicates: list[str]) -> str:
    names = ", ".join(f'"{name}"' for name in duplicates)
    return (
        f"The query returns more than one column named {names}. "
        "Names that differ only by case count as duplicates. "
        "Give each output column a unique name, for example with an alias."
    )
