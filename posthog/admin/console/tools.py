import re
import dataclasses
from typing import TYPE_CHECKING, ClassVar, Protocol
from urllib.parse import urlencode

from django import forms
from django.urls import reverse

from posthog.admin.console.panels import Gate, Owner, Tone, check_danger, is_internal_path
from posthog.admin.console.records import RECORD_TYPES
from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from django.db.models import Model
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
    # On a table with a TableSelect, what this row's checkbox submits. Empty for a row that staff cannot pick.
    select_value: str = ""


@frozen
class TableSelect:
    """A checkbox on each row of a Table, and a button that opens the tool operation `operation_key` with the
    ticked rows in its field `field`, a multiple choice field.

    The button opens the operation's form by GET, so staff still review it and give a reason before anything runs.
    `values` go along as hidden fields, for example the filters, so the way back keeps them. Only a tool page holds
    a selectable table, for an operation the tool offers.
    """

    operation_key: str
    field: str
    label: str
    values: dict[str, str] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.field in self.values:
            raise ValueError(f"TableSelect values must not set {self.field!r}, which the checkboxes set")


@frozen
class GroupRow:
    """A full-width row that heads the rows below it, for example an organization above its teams."""

    text: str
    detail: str = ""
    href: str | None = None


@frozen
class ProgressPart:
    count: int
    tone: Tone


@frozen
class Progress:
    """How much of a known total is done, as a bar above a table. `parts` fill it in order, then `moving` pulses.

    Count in `moving` only what can still finish, so the bar does not pulse for a part that will never fill.
    """

    text: str
    total: int
    parts: tuple[ProgressPart, ...]
    moving: int = 0

    def __post_init__(self) -> None:
        counts = [*(part.count for part in self.parts), self.moving]
        if self.total <= 0 or min(counts) < 0 or sum(counts) > self.total:
            raise ValueError(f"Progress parts {counts} do not fit a total of {self.total}")

    @property
    def filled(self) -> int:
        return sum(part.count for part in self.parts)

    # Strings, because a template would write a float with a decimal comma in some locales.
    def bars(self) -> list[tuple[Tone, str]]:
        return [(part.tone, f"{part.count / self.total * 100:.3f}") for part in self.parts if part.count]

    def moving_percent(self) -> str:
        return f"{self.moving / self.total * 100:.3f}"


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
    progress: Progress | None = None
    select: TableSelect | None = None


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
    # Lays the fields out side by side on a wide screen, for a group of short inputs.
    inline: bool = False


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
    # Puts every field and the button on one line without the group cards, for a few short filters above a page
    # that needs the room.
    compact: bool = False

    def __post_init__(self) -> None:
        grouped = [name for group in self.groups for name in group.field_names]
        expected = [field.name for field in self.form.visible_fields()]
        # _filters.html renders only the fields a group names, so a missing one would vanish without an error.
        if sorted(grouped) != sorted(expected):
            raise ValueError(f"Filter groups must name each form field once. Fields: {expected}, groups: {grouped}")

    def bound_groups(self) -> list[tuple[FieldGroup, list["BoundField"]]]:
        return [(group, [self.form[name] for name in group.field_names]) for group in self.groups]


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


@frozen
class Choice:
    label: str
    value: str
    # SUCCESS makes the button the primary one, and DESTRUCTIVE gives it a red outline.
    tone: Tone | None = None
    # The key that presses the button, as KeyboardEvent.key names it, for example ArrowRight.
    key: str = ""


@frozen
class Decision:
    """One item that staff decide on, such as a card to label, with a button per choice that runs a tool operation
    at once, without its form page.

    A button posts the form of the operation `operation_key`: `values` as hidden fields, the choice's value in the
    field `field`, and what staff typed in the field `note_field` when it is set. The post keeps `query`, and the
    console returns to the tool page with it, so `query` can point the page at the next item. Only a tool page holds
    a Decision, for an operation the tool offers that has a form and no danger.
    """

    kind: ClassVar[str] = "decision"
    title: str
    text: str
    operation_key: str
    field: str
    choices: tuple[Choice, ...]
    values: dict[str, str] = dataclasses.field(default_factory=dict)
    # One muted line above the title, for example where the item comes from.
    detail: str = ""
    note_field: str = ""
    note_label: str = ""
    note: str = ""
    query: str = ""
    # A link to the next item without a decision. `skip_key` presses it, like `Choice.key`.
    skip_href: str | None = None
    skip_key: str = ""

    def __post_init__(self) -> None:
        if not self.choices:
            raise ValueError(f"Decision {self.title!r} needs at least one choice")
        # The buttons and the note set these fields, so a hidden value with the same name would be posted twice.
        clashes = {self.field, self.note_field} & set(self.values)
        if clashes:
            raise ValueError(f"Decision values must not set {sorted(clashes)}, which the buttons and note set")
        if self.query.startswith("?"):
            raise ValueError("Decision query is the query string without its leading ?")
        if self.skip_href is not None and not is_internal_path(self.skip_href):
            raise ValueError(f"Decision skip link {self.skip_href!r} must be a path that starts with /")


Block = Notice | Table | Paging | Output | Stats | Links | Filters | Live | Secret | Decision
INNER_BLOCKS = Notice | Table | Output | Stats


def _check_table(table: Table) -> None:
    for row in table.rows:
        if isinstance(row, Row) and len(row.cells) != len(table.columns):
            raise ValueError(f"A table row has {len(row.cells)} cells for {len(table.columns)} columns")
        if isinstance(row, Row) and row.select_value and table.select is None:
            raise ValueError("A table row has a select_value, but its table has no select")


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
            # A refresh replaces the table, which would clear the rows staff ticked.
            if isinstance(block, Live) and isinstance(inner, Table) and inner.select is not None:
                raise ValueError(f"Live block {block.key!r} holds a selectable table. Put it outside the Live block.")

    def check_operations(self, operations: "list[ToolOperation]") -> "Page":
        """Refuses a block that would open an operation the tool does not offer.

        A Decision posts at once, so it also needs a form and no danger, which would ask for a reason and a confirm
        page that a single click skips. A selectable table needs the multiple choice field it fills.
        """
        offered = {operation.key: operation for operation in operations}
        for block in self.blocks:
            if isinstance(block, Decision):
                operation = offered.get(block.operation_key)
                if operation is None or operation.form_class is None or operation.danger:
                    raise ValueError(
                        f"Decision {block.title!r} runs {block.operation_key!r}, which the tool must offer with a "
                        "form and without danger"
                    )
            elif isinstance(block, Table) and block.select is not None:
                operation = offered.get(block.select.operation_key)
                form_class = operation.form_class if operation else None
                field = form_class.base_fields.get(block.select.field) if form_class else None
                if not isinstance(field, forms.MultipleChoiceField):
                    raise ValueError(
                        f"A table selects for {block.select.operation_key!r}, which the tool must offer with a "
                        f"multiple choice field {block.select.field!r}"
                    )
        return self

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
    # False for an operation that a Decision block or a selectable table opens, so the Actions card does not offer
    # its form as well.
    listed: bool = True

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
    # None when no team owns the data behind the tool. The console then shows no owner badge.
    owner: ClassVar[Owner | None]
    group: ClassVar[str]
    description: ClassVar[str] = ""
    # The RECORD_TYPES key of the one record a tool is about. The tool reads the record from the query parameter of the
    # same name, for example ?team=7, and its breadcrumb runs through that record.
    subject: ClassVar[str | None] = None

    def subject_of(self, request: "HttpRequest") -> "Model | None":
        if self.subject is None:
            return None
        # The breadcrumb, page() and live() each ask for the record, so one request looks it up once.
        found: dict[tuple[str, str], Model | None] = request.__dict__.setdefault("console_subjects", {})
        key = (self.subject, request.GET.get(self.subject, ""))
        if key not in found:
            found[key] = RECORD_TYPES[self.subject].find(key[1])
        return found[key]

    @classmethod
    def url_for(cls, obj: "Model") -> str:
        if cls.subject is None:
            raise ValueError(f"Tool {cls.key!r} has no subject, so it has no page for one record")
        return f"{reverse('admin_console_tool', kwargs={'tool_key': cls.key})}?{urlencode({cls.subject: obj.pk})}"

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
