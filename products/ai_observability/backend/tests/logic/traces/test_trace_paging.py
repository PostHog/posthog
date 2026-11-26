from datetime import UTC, datetime, timedelta

import pytest

from products.ai_observability.backend.logic.traces.trace_paging import (
    RowsAfter,
    RowsAround,
    RowsBefore,
    SelectionPage,
    around_takes,
    next_cursor,
    page_after,
    page_around,
    page_before,
    previous_cursor,
)
from products.ai_observability.backend.logic.traces.trace_selection import TracePosition, decode_cursor

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
SESSION = tuple(
    TracePosition(trace_id=f"t{index}", first_timestamp=T0 + timedelta(minutes=index)) for index in range(1, 13)
)


def ids(positions: tuple[TracePosition, ...]) -> list[str]:
    return [position.trace_id for position in positions]


def rows_around(anchor: int | None, limit: int) -> RowsAround:
    takes = around_takes(limit)
    start = 0 if anchor is None else anchor - 1
    return RowsAround(
        before=tuple(reversed(SESSION[:start]))[: takes.before], from_anchor=SESSION[start : start + takes.from_anchor]
    )


def trace_ids(*positions: TracePosition | None) -> list[str | None]:
    return [position.trace_id if position else None for position in positions]


@pytest.mark.parametrize(
    "anchor, limit, expected, previous, next_after",
    [
        (6, 4, ["t4", "t5", "t6", "t7"], "t3", "t7"),
        (1, 4, ["t1", "t2", "t3", "t4"], None, "t4"),
        (12, 4, ["t10", "t11", "t12"], "t9", None),
        (3, 1, ["t3"], "t2", "t3"),
        (2, 5, ["t1", "t2", "t3", "t4", "t5"], None, "t5"),
        (None, 4, ["t1", "t2", "t3", "t4"], None, "t4"),
    ],
    ids=["middle", "first row", "last row", "one slot", "fewer rows before than half", "anchor not held"],
)
def test_page_around_puts_about_half_the_page_before_the_anchor(
    anchor: int | None, limit: int, expected: list[str], previous: str | None, next_after: str | None
) -> None:
    page = page_around(rows_around(anchor, limit), limit)

    assert (ids(page.positions), trace_ids(page.previous, page.next_after)) == (expected, [previous, next_after])


@pytest.mark.parametrize(
    "read, expected, previous, next_after",
    [
        (RowsBefore(positions=tuple(reversed(SESSION[1:5]))), ["t4", "t5"], "t3", "t5"),
        (RowsBefore(positions=tuple(reversed(SESSION[:2]))), ["t1", "t2"], None, "t2"),
        (RowsBefore(positions=()), [], None, ""),
    ],
    ids=["more before", "reaches the start", "nothing before the bound"],
)
def test_page_before_reads_back_from_the_bound_and_always_leads_on(
    read: RowsBefore, expected: list[str], previous: str | None, next_after: str
) -> None:
    page = page_before(read, 2, SESSION[5])

    assert (ids(page.positions), trace_ids(page.previous, page.next_after)) == (expected, [previous, next_after])


def test_the_page_after_an_empty_page_before_starts_at_the_bound() -> None:
    page = page_before(RowsBefore(positions=()), 2, SESSION[0])

    assert decode_cursor(next_cursor(page) or "").sort_key == SESSION[0].sort_key


@pytest.mark.parametrize(
    "read, expected, previous, next_after",
    [
        (RowsAfter(positions=SESSION[:3], previous=None), ["t1", "t2"], None, "t2"),
        (RowsAfter(positions=SESSION[10:], previous=SESSION[9]), ["t11", "t12"], "t10", None),
    ],
    ids=["first page", "last page"],
)
def test_page_after_reads_forward_from_the_bound(
    read: RowsAfter, expected: list[str], previous: str | None, next_after: str | None
) -> None:
    page = page_after(read, 2)

    assert (ids(page.positions), trace_ids(page.previous, page.next_after)) == (expected, [previous, next_after])


def test_cursors_point_at_the_edges_of_the_page() -> None:
    page = SelectionPage(positions=SESSION[3:6], previous=SESSION[2], next_after=SESSION[5])

    assert (decode_cursor(previous_cursor(page) or ""), decode_cursor(next_cursor(page) or "")) == (
        SESSION[3],
        SESSION[5],
    )


def test_an_empty_page_past_a_cursor_has_no_cursors() -> None:
    page = page_after(RowsAfter(positions=(), previous=SESSION[11]), 2)

    assert (previous_cursor(page), next_cursor(page)) == (None, None)
