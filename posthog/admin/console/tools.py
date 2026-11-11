import re
import dataclasses
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
    # An optional link after the text, for example back to the list a sub-page came from.
    link_text: str = ""
    href: str | None = None

    def __post_init__(self) -> None:
        if self.href is not None and (not self.href.startswith("/") or self.href.startswith("//")):
            raise ValueError(f"Notice links to {self.href!r}. Link to a PostHog path that starts with /.")


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


@frozen
class Live:
    """A block that the page refreshes from the server while `refresh_seconds` is set, for example the runs of a
    job that is still going. Set it to None when nothing is running, and the page stops asking.

    The tool builds it in `ConsoleTool.live`, and `page` embeds the same call, so the first render and every
    refresh come from one place.
    """

    kind: ClassVar[str] = "live"
    # Stable across requests: the page asks for the block by this key, not by its position.
    key: str
    block: "Notice | Table | Output"
    refresh_seconds: int | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.key):
            raise ValueError(f"Live block key {self.key!r} must be lowercase and dash-separated, like a URL slug")


@frozen
class Secret:
    """A credential that staff must copy now, for example a password the control plane returns only once.

    Only an operation's result page may show one. The console keeps the result for one read and then
    forgets it, so the value is never in the audit log, a confirm token, a URL or a message.
    """

    kind: ClassVar[str] = "secret"
    label: str
    value: str = dataclasses.field(repr=False)
    note: str = "Copy it now. It is not shown again."


Block = Notice | Table | Paging | Output | Live | Secret
INNER_BLOCKS = Notice | Table | Output


def _check_table(table: Table) -> None:
    for row in table.rows:
        if isinstance(row, Row) and len(row.cells) != len(table.columns):
            raise ValueError(f"A table row has {len(row.cells)} cells for {len(table.columns)} columns")


@frozen
class Page:
    blocks: tuple[Block, ...]

    def __post_init__(self) -> None:
        # tool.html renders only the block kinds it knows, so an unknown block would vanish without an error.
        for block in self.blocks:
            if not isinstance(block, Notice | Table | Paging | Output | Live | Secret):
                raise ValueError(f"{type(block).__name__} is not a console block. Add new blocks to the shell.")
            if isinstance(block, Live) and not isinstance(block.block, INNER_BLOCKS):
                raise ValueError(
                    f"Live block {block.key!r} holds a {type(block.block).__name__}, not a table, notice or output"
                )
            inner = block.block if isinstance(block, Live) else block
            if isinstance(inner, Table):
                _check_table(inner)

    def refuse_secrets(self, where: str) -> "Page":
        if any(isinstance(block, Secret) for block in self.blocks):
            raise ValueError(f"A {where} shows a Secret block. Return secrets only from an operation's result page.")
        return self


class ToolOperationHandler(Protocol):
    """Returns None when done, and the console sends staff back to the tool with the messages the handler added.

    It may return a `Page` instead, which the console shows once as the result. A reload does not run the
    operation again. A `Secret` block may appear only on such a result page.
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

    def live(self, request: "HttpRequest", key: str) -> Live | None:
        """The live block with this key, for the page's refreshes. None when the tool has no such block."""
        return None
