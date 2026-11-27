from typing import Final

from posthog.paging import PageRequest

# ClickHouse refuses a groupArraySorted size above this, so a page read sorts at most this many groups. An offset past
# it reads an empty page, and the counts still cover every group.
MAX_SORTED_GROUPS: Final = 16_777_215


def groups_to_sort(page: PageRequest) -> int:
    """How many of the first groups a page read sorts, from which it keeps the page's own."""
    return min(page.offset + page.limit, MAX_SORTED_GROUPS)
