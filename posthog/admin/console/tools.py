from typing import TYPE_CHECKING, ClassVar

from posthog.admin.console.panels import Owner, Tone
from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from django.http import HttpRequest


@frozen
class Cell:
    text: str
    href: str | None = None
    tone: Tone | None = None
    mono: bool = False
    muted: bool = False


@frozen
class Row:
    cells: tuple[Cell, ...]


@frozen
class GroupRow:
    """A full-width row that heads the rows below it, for example an organization above its teams."""

    text: str
    detail: str = ""
    href: str | None = None


@frozen
class Table:
    kind: ClassVar[str] = "table"
    columns: tuple[str, ...]
    rows: tuple[Row | GroupRow, ...]
    empty_text: str = "Nothing to show."


@frozen
class Notice:
    kind: ClassVar[str] = "notice"
    text: str


@frozen
class Paging:
    kind: ClassVar[str] = "paging"
    number: int
    num_pages: int
    summary: str
    previous_url: str | None
    next_url: str | None


Block = Notice | Table | Paging


@frozen
class Page:
    blocks: tuple[Block, ...]


class ConsoleTool:
    """A console page that is not about one record, for example a report across all teams.

    A tool returns a `Page` of blocks. The console renders it, so tools need no templates.
    Subclass it in `<app>/console.py` and register it with `console.register_tool`.
    Read posthog/admin/console/AGENTS.md before you add one.
    """

    key: ClassVar[str]
    title: ClassVar[str]
    owner: ClassVar[Owner]
    group: ClassVar[str]
    description: ClassVar[str] = ""

    def page(self, request: "HttpRequest") -> Page:
        raise NotImplementedError
