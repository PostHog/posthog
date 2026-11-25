from dataclasses import replace

from posthog.dataclasses import frozen

from .trace_selection import TracePosition, encode_cursor


@frozen
class RowsAfter:
    """Rows read forward from a bound, in the selection's order, and the nearest row at or before the bound."""

    positions: tuple[TracePosition, ...]
    previous: TracePosition | None


@frozen
class RowsBefore:
    """Rows read backward from a bound, the one next to the bound first."""

    positions: tuple[TracePosition, ...]


@frozen
class RowsAround:
    """Rows read on both sides of an anchor trace. Without the anchor, `before` is empty and `from_anchor` holds the
    selection's first rows."""

    before: tuple[TracePosition, ...]
    from_anchor: tuple[TracePosition, ...]


@frozen
class AroundTakes:
    before: int
    from_anchor: int


@frozen
class SelectionPage:
    """`previous` is the row right before the page, None when the page starts the selection. `next_after` is where
    the next page reads from, None when the page ends the selection."""

    positions: tuple[TracePosition, ...]
    previous: TracePosition | None
    next_after: TracePosition | None


def rows_to_read(limit: int) -> int:
    """One row past the page tells a page that ends the selection from one that does not."""
    return limit + 1


def around_takes(limit: int) -> AroundTakes:
    # A page of one slot still reads one row before, to know there is a page before and which row it ends on.
    return AroundTakes(before=limit // 2 + 1, from_anchor=rows_to_read(limit))


def _last_if_more(positions: tuple[TracePosition, ...], read: int, limit: int) -> TracePosition | None:
    return positions[-1] if read > limit and positions else None


def page_after(rows: RowsAfter, limit: int) -> SelectionPage:
    positions = rows.positions[:limit]
    return SelectionPage(
        positions=positions, previous=rows.previous, next_after=_last_if_more(positions, len(rows.positions), limit)
    )


def page_before(rows: RowsBefore, limit: int, bound: TracePosition) -> SelectionPage:
    """Rows after the bound always follow a page read back from it, so the page always has a next page. When nothing
    precedes the bound, that next page starts at the bound."""
    positions = tuple(reversed(rows.positions[:limit]))
    return SelectionPage(
        positions=positions,
        previous=rows.positions[limit] if len(rows.positions) > limit else None,
        next_after=positions[-1] if positions else _just_before(bound),
    )


def _just_before(bound: TracePosition) -> TracePosition:
    # Trace ids are never empty, so in either order no held row sorts between this key and the bound's.
    return replace(bound, trace_id="")


def page_around(rows: RowsAround, limit: int) -> SelectionPage:
    """About half the page before the anchor, then the anchor and what follows it. A page around a trace the selection
    does not hold is its first page."""
    half = limit // 2
    kept = tuple(reversed(rows.before[:half]))
    take = limit - len(kept)
    positions = (*kept, *rows.from_anchor[:take])
    return SelectionPage(
        positions=positions,
        previous=rows.before[half] if len(rows.before) > half else None,
        next_after=_last_if_more(positions, len(rows.from_anchor), take),
    )


def previous_cursor(page: SelectionPage) -> str | None:
    return encode_cursor(page.positions[0]) if page.previous is not None and page.positions else None


def next_cursor(page: SelectionPage) -> str | None:
    return encode_cursor(page.next_after) if page.next_after is not None else None
