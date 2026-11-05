from typing import TYPE_CHECKING, ClassVar, Protocol

from django import forms

from posthog.admin.console.panels import Gate, Owner, Tone, check_danger
from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse


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
class Output:
    """Plain text output, for example what a management command printed. The shell shows it as written."""

    kind: ClassVar[str] = "output"
    text: str


@frozen
class Paging:
    kind: ClassVar[str] = "paging"
    number: int
    num_pages: int
    summary: str
    previous_url: str | None
    next_url: str | None


Block = Notice | Table | Paging | Output


@frozen
class Page:
    blocks: tuple[Block, ...]

    def __post_init__(self) -> None:
        # tool.html renders only the block kinds it knows, so an unknown block would vanish without an error.
        for block in self.blocks:
            if not isinstance(block, Notice | Table | Paging | Output):
                raise ValueError(f"{type(block).__name__} is not a console block. Add new blocks to the shell.")
            if isinstance(block, Table):
                for row in block.rows:
                    if isinstance(row, Row) and len(row.cells) != len(block.columns):
                        raise ValueError(f"A table row has {len(row.cells)} cells for {len(block.columns)} columns")


class ToolOperationHandler(Protocol):
    """Returns None when done, and the console sends staff back to the tool with the messages the handler added.

    It may return a `Page` instead, which the console shows as the result. Do that only when running the
    operation again is harmless, for example a dry run, because reloading a result page submits the form again.
    To report a failure, add an error message and return a 4xx or 5xx response.
    """

    def __call__(self, request: "HttpRequest", form: forms.Form | None) -> "HttpResponse | Page | None": ...


class PreviewHandler(Protocol):
    """Shows what an operation would change before it runs, as a `Page`. It must not change anything.

    To refuse the input, for example when no record matches, add an error to the form; the console then shows
    the form again.
    """

    def __call__(self, request: "HttpRequest", form: forms.Form) -> "Page": ...


@frozen
class ToolOperation:
    """An action a tool offers, for example starting a backfill. Like a record `Operation`, without a record."""

    key: str
    label: str
    handler: ToolOperationHandler
    danger: bool = False
    form_class: type[forms.Form] | None = None
    form_initial: dict[str, object] | None = None
    description: str = ""
    undo_hint: str = ""
    gate: Gate | None = None
    # Staff confirm on a page that shows what will change. For actions on many records, such as a bulk change.
    preview: PreviewHandler | None = None

    def __post_init__(self) -> None:
        check_danger(self.key, self.danger, self.form_class, self.undo_hint)
        if self.preview is not None and self.form_class is None:
            raise ValueError(f"Operation {self.key!r} has a preview, so it needs a form for the preview to read")


class ConsoleTool:
    """A console page that is not about one record, for example a report across all teams.

    A tool returns a `Page` of blocks and, optionally, operations. The console renders both, so tools need no
    templates.
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

    def operations(self, request: "HttpRequest") -> list[ToolOperation]:
        """The actions the tool page offers. The console runs them; `page` stays read-only."""
        return []
