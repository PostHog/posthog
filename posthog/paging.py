"""Framework-free page types that facades take and return.

A facade cannot hand a queryset to a DRF paginator, because contracts stay free of Django and DRF.
It takes a page request, pages in SQL and returns the page with the total, so presentation can build
the standard `count`/`next`/`previous`/`results` response from it.
"""

from collections.abc import Callable

from posthog.dataclasses import frozen


@frozen
class PageRequest:
    """One page of a list that pages by offset."""

    limit: int
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError(f"A page holds at least one item, got limit={self.limit}.")
        if self.offset < 0:
            raise ValueError(f"A page cannot start before the first item, got offset={self.offset}.")


@frozen
class CursorBound:
    """Where a cursor page starts.

    Only the items whose first ordering field sorts before `value` (when `before`) or after it
    (otherwise) are on the page. `value` is the field's value as text, as an API cursor carries it.
    """

    value: str
    before: bool


@frozen
class CursorPageRequest:
    """One page of a list that pages by cursor.

    `ordering` names the fields to sort by, most significant first. A leading `-` sorts that field
    in descending order. The page skips `offset` items past `bound` and holds at most `limit` items.
    """

    ordering: tuple[str, ...]
    bound: CursorBound | None
    offset: int
    limit: int

    def __post_init__(self) -> None:
        if not self.ordering:
            raise ValueError("A cursor page needs at least one ordering field.")
        if self.limit < 1:
            raise ValueError(f"A page holds at least one item, got limit={self.limit}.")
        if self.offset < 0:
            raise ValueError(f"A page cannot start before the bound, got offset={self.offset}.")


@frozen
class Page[T]:
    """The items of one page, and how many items the whole list holds."""

    results: list[T]
    count: int

    def map[U](self, convert: Callable[[T], U]) -> "Page[U]":
        """Return the same page with each item converted, for example from a model to a contract."""
        return Page(results=[convert(item) for item in self.results], count=self.count)
