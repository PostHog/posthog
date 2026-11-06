from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

from django import forms

from posthog.admin.console.panels import Owner, Tone, check_danger_contract
from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from django.forms.boundfield import BoundField
    from django.http import HttpRequest, HttpResponse


@frozen
class Cell:
    text: str
    href: str | None = None
    tone: Tone | None = None
    mono: bool = False
    muted: bool = False
    detail: str = ""


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
    title: str = ""
    numeric_columns: tuple[int, ...] = ()


@frozen
class Notice:
    """Plain text under the title. With a tone it becomes a callout, for something staff must not miss."""

    kind: ClassVar[str] = "notice"
    text: str
    tone: Tone | None = None


@frozen
class Paging:
    kind: ClassVar[str] = "paging"
    number: int
    num_pages: int
    summary: str
    previous_url: str | None
    next_url: str | None


@frozen
class Stat:
    label: str
    value: str
    tone: Tone | None = None


@frozen
class Stats:
    """The few numbers staff read first, as a row of cards."""

    kind: ClassVar[str] = "stats"
    items: tuple[Stat, ...]


@frozen
class Link:
    label: str
    href: str
    primary: bool = False
    pending_label: str = ""


@frozen
class Links:
    """Navigation buttons. A link only reads, so anything that changes state is a `ToolOperation`."""

    kind: ClassVar[str] = "links"
    items: tuple[Link, ...]


@frozen
class FieldGroup:
    title: str
    field_names: tuple[str, ...]


@frozen
class Filters:
    """A form that submits by GET, so the page it opens can be reloaded and shared.

    Bind the form to `request.GET` when the query holds its values, so the page shows what staff typed.
    """

    kind: ClassVar[str] = "filters"
    form: forms.Form
    groups: tuple[FieldGroup, ...]
    submit_label: str
    pending_label: str = ""

    def __post_init__(self) -> None:
        grouped = [name for group in self.groups for name in group.field_names]
        expected = [field.name for field in self.form.visible_fields()]
        # filters.html renders only the fields a group names, so a missing one would vanish without an error.
        if sorted(grouped) != sorted(expected):
            raise ValueError(f"Filter groups must name each form field once. Fields: {expected}, groups: {grouped}")

    def bound_groups(self) -> list[tuple[str, list["BoundField"]]]:
        return [(group.title, [self.form[name] for name in group.field_names]) for group in self.groups]


class ToolOperationHandler(Protocol):
    """Returns None when done, and the console reloads the tool page. Return a redirect to go somewhere else.

    To report a failure, add an error message and return a 4xx or 5xx response. The console then shows
    the page again with what staff typed.
    """

    def __call__(self, request: "HttpRequest", form: forms.Form) -> "HttpResponse | None": ...


@frozen
class ToolOperation:
    """An action a tool offers. It always has a form, because it is not about one record staff can see."""

    key: str
    label: str
    handler: ToolOperationHandler
    form_class: type[forms.Form]
    danger: bool = False
    description: str = ""
    undo_hint: str = ""

    def __post_init__(self) -> None:
        check_danger_contract(key=self.key, danger=self.danger, form_class=self.form_class, undo_hint=self.undo_hint)


@frozen
class OperationForm:
    """Where a tool page shows the form of an operation it offers. The console fills in `form`."""

    kind: ClassVar[str] = "operation_form"
    operation: ToolOperation
    initial: Mapping[str, Any] | None = None
    pending_label: str = ""
    form: forms.Form | None = None


Block = Notice | Table | Paging | Stats | Links | Filters | OperationForm
BLOCK_TYPES = (Notice, Table, Paging, Stats, Links, Filters, OperationForm)


@frozen
class Page:
    blocks: tuple[Block, ...]
    refresh_seconds: int | None = None

    def __post_init__(self) -> None:
        # tool.html renders only the block kinds it knows, so an unknown block would vanish without an error.
        for block in self.blocks:
            if not isinstance(block, BLOCK_TYPES):
                raise ValueError(f"{type(block).__name__} is not a console block. Add new blocks to the shell.")
            if isinstance(block, Table):
                for row in block.rows:
                    if isinstance(row, Row) and len(row.cells) != len(block.columns):
                        raise ValueError(f"A table row has {len(row.cells)} cells for {len(block.columns)} columns")


class ConsoleTool:
    """A console page that is not about one record, for example a report across all teams.

    A tool returns a `Page` of blocks. The console renders it, so tools need no templates.
    `page` only reads. Anything that changes state is a `ToolOperation` from `operations`.
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
        return []
