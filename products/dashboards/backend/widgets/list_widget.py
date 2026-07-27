from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ListWidgetPage:
    """One fetched page of a list widget query: the raw rows plus pagination flags."""

    results: list[Any]
    has_more: bool
    next_offset: int | None = None


def run_list_widget(
    *,
    limit: int,
    count_cap: int,
    include_total_count: bool,
    fetch_page: Callable[[int], ListWidgetPage],
    log_key: str,
    transform_row: Callable[[Any], Any] = lambda row: row,
    offset: int = 0,
) -> dict[str, Any]:
    """Run a list widget query and assemble the shared pagination payload.

    `fetch_page(page_limit)` builds and runs the underlying query at the given limit and
    returns the raw rows plus whether more exist. It is called once for the visible page
    (`limit`) and, when that page has more, again at `count_cap` to derive the `totalCount`
    shown in the list footer (`totalCountCapped` when the count itself hits the cap).
    """
    page = fetch_page(limit)
    results = [transform_row(row) for row in page.results[:limit]]
    has_more = page.has_more
    shown = len(results)

    payload: dict[str, Any] = {
        "results": results,
        "hasMore": has_more,
        "limit": limit,
        "offset": offset,
    }

    if has_more:
        if include_total_count:
            try:
                count_page = fetch_page(count_cap)
                payload["totalCount"] = len(count_page.results)
                payload["totalCountCapped"] = count_page.has_more
            except Exception:
                logger.exception(log_key)
                payload["totalCount"] = shown
                payload["totalCountCapped"] = True
    else:
        payload["totalCount"] = shown
        payload["totalCountCapped"] = False

    if page.next_offset is not None:
        payload["nextOffset"] = page.next_offset

    return payload
