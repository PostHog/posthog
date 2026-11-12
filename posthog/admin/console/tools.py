import re
import dataclasses
from typing import TYPE_CHECKING, ClassVar, Protocol

from django import forms

from posthog.admin.console.panels import Gate, Owner, Tone, check_danger, is_internal_path
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
    # For a long table above something staff must reach. It scrolls inside its card instead of growing the page.
    scrolls: bool = False


@frozen
class Notice:
    """Plain text under the title. With a tone it becomes a callout, for something staff must not miss."""

    kind: ClassVar[str] = "notice"
    text: str
    tone: Tone | None = None
    # An optional link after the text, for example back to the list a sub-page came from.
    link_text: str = ""
    href: str | None = None

    def __post_init__(self) -> None:
        if self.href is not None and not is_internal_path(self.href):
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

    def __post_init__(self) -> None:
        if not is_internal_path(self.href):
            raise ValueError(f"Link {self.label!r} links to {self.href!r}. Link to a PostHog path that starts with /.")


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
        # _filters.html renders only the fields a group names, so a missing one would vanish without an error.
        if sorted(grouped) != sorted(expected):
            raise ValueError(f"Filter groups must name each form field once. Fields: {expected}, groups: {grouped}")

    def bound_groups(self) -> list[tuple[str, list["BoundField"]]]:
        return [(group.title, [self.form[name] for name in group.field_names]) for group in self.groups]


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
    block: "Notice | Table | Output | Stats"
    refresh_seconds: int | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.key):
            raise ValueError(f"Live block key {self.key!r} must be lowercase and dash-separated, like a URL slug")
        # The live endpoint renders this block on every refresh, so a Secret here would be shown again and again.
        if not isinstance(self.block, INNER_BLOCKS):
            raise ValueError(
                f"Live block {self.key!r} holds a {type(self.block).__name__}, not a table, notice, output or stats"
            )


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


Block = Notice | Table | Paging | Output | Stats | Links | Filters | Live | Secret
INNER_BLOCKS = Notice | Table | Output | Stats


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
            if not isinstance(block, Block):
                raise ValueError(f"{type(block).__name__} is not a console block. Add new blocks to the shell.")
            inner = block.block if isinstance(block, Live) else block
            if isinstance(inner, Table):
                _check_table(inner)

    def refuse_secrets(self, where: str) -> "Page":
        if any(isinstance(block, Secret) for block in self.blocks):
            raise ValueError(f"A {where} shows a Secret block. Return secrets only from an operation's result page.")
        return self


@frozen
class Download:
    """A file a tool hands staff, for example a certificate as JSON. The console serves it as an attachment."""

    filename: str
    content_type: str
    content: str | bytes

    def __post_init__(self) -> None:
        # The name goes into the Content-Disposition header, so a quote or a line break would break the header.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", self.filename):
            raise ValueError(f"Download name {self.filename!r} must use only letters, digits, dots, dashes and _")


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
    # The run button shows this until the next page loads, for an operation that takes a while.
    pending_label: str = ""

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

    def app_page(self, request: "HttpRequest") -> "HttpResponse | None":
        """A page the product renders itself, such as a React app that blocks cannot express. The console serves it
        in place of `page` and `operations`, for GET and HEAD only. None for a tool built from blocks."""
        return None

    def operations(self, request: "HttpRequest") -> list[ToolOperation]:
        """The actions the tool page offers. The console runs them; `page` stays read-only."""
        return []

    def live(self, request: "HttpRequest", key: str) -> Live | None:
        """The live block with this key, for the page's refreshes. None when the tool has no such block."""
        return None

    def download(self, request: "HttpRequest", key: str) -> Download | None:
        """The file with this key, for a link on the page. It only reads, like `page`. None when there is no such file."""
        return None
