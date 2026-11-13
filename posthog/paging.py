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
class CursorPageRequest:
    """One page of a list that pages by cursor.

    `ordering` names the fields to sort by, most significant first. A leading `-` sorts that field
    in descending order. `after` holds the values of the leading ordering fields of the item just
    before the page, as text the way an API cursor carries them, with None for a NULL. The page
    holds at most `limit` of the items that sort strictly after that item, past the first `offset`
    of them. An empty `after` starts at the first item.
    """

    ordering: tuple[str, ...]
    after: tuple[str | None, ...]
    offset: int
    limit: int

    def __post_init__(self) -> None:
        if not self.ordering:
            raise ValueError("A cursor page needs at least one ordering field.")
        if len(self.after) > len(self.ordering):
            raise ValueError(f"A cursor holds one value per ordering field, got {len(self.after)} values.")
        if self.limit < 1:
            raise ValueError(f"A page holds at least one item, got limit={self.limit}.")
        if self.offset < 0:
            raise ValueError(f"A page cannot start before the cursor, got offset={self.offset}.")


@frozen
class Page[T]:
    """The items of one page, and how many items the whole list holds."""

    results: list[T]
    count: int

    def map[U](self, convert: Callable[[T], U]) -> "Page[U]":
        """Return the same page with each item converted, for example from a model to a contract."""
        return Page(results=[convert(item) for item in self.results], count=self.count)
