from typing import Final

from posthog.hogql import ast

from posthog.paging import PageRequest

# ClickHouse refuses a groupArraySorted size above this, so a page read sorts at most this many groups. An offset past
# it reads an empty page, and the counts still cover every group.
MAX_SORTED_GROUPS: Final = 16_777_215


def groups_to_sort(page: PageRequest) -> int:
    """How many of the first groups a page read sorts, from which it keeps the page's own."""
    return min(page.offset + page.limit, MAX_SORTED_GROUPS)


def page_of(sorted_groups: ast.Expr, page: PageRequest) -> ast.Expr:
    """The page's own groups of the groups a page read sorts, so that a deep page returns no more rows than a first
    one."""
    return ast.Call(
        name="arraySlice",
        args=[sorted_groups, ast.Constant(value=page.offset + 1), ast.Constant(value=page.limit)],
    )
