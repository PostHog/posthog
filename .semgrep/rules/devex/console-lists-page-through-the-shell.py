# Test cases for console-lists-page-through-the-shell.
# ruff: noqa


def hand_built(page):
    # ruleid: console-lists-page-through-the-shell
    return Paging(number=page.number, num_pages=3, summary="3 teams", previous_url=None, next_url="?page=2")


def through_the_shell(request, page):
    # ok: console-lists-page-through-the-shell
    return Paging.build(request, number=page.number, num_pages=page.num_pages, count=page.count, noun="team")
