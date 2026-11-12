from collections.abc import Callable
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Protocol

from django import forms
from django.utils.safestring import SafeData

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from django.db.models import Model
    from django.http import HttpRequest, HttpResponse

    from posthog.admin.console.tools import Page


class Tone(StrEnum):
    DEFAULT = "default"
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    DESTRUCTIVE = "destructive"


@frozen
class Owner:
    name: str
    # Slug of a mini crest from @posthog/brand, for example "workflows". The build ships only the crests named here.
    crest: str
    # The Django group whose members may run this team's operations gated with Gate.owner().
    staff_group: str | None = None


# A card with more facts than this is a report. Put the detail in a tool and link to it.
MAX_FACTS_PER_PANEL = 8


@frozen
class Fact:
    label: str
    value: str
    tone: Tone | None = None
    mono: bool = False
    # A console page the value links to, for example the team page of a team the fact names.
    href: str | None = None

    def __post_init__(self) -> None:
        # The shell escapes facts. Markup from format_html or mark_safe would bypass the shared design.
        if isinstance(self.label, SafeData) or isinstance(self.value, SafeData):
            raise ValueError(f"Fact {self.label!r} must be plain text, not markup")
        # Facts link within PostHog only, so a value that came from customer data cannot become an outside link.
        # Browsers read a leading "/\\" like "//", so both would leave the site.
        if self.href is not None and (not self.href.startswith("/") or self.href.startswith(("//", "/\\"))):
            raise ValueError(f"Fact {self.label!r} links to {self.href!r}. Link to a PostHog path that starts with /.")


def _unresolved_owner_gate(request: "HttpRequest") -> bool:
    # The shell resolves Gate.owner() against the panel or tool owner before it checks anything. Code that checks
    # the unresolved gate is a bug, and letting nobody through keeps that bug from opening the operation.
    return False


@frozen
class Gate:
    """Who may run an operation, on top of the staff check that every console page has.

    Use `Gate.owner()`, or a Django group or a reviewed rule for the rare case across teams. Not a Django model
    permission: `User.is_superuser` mirrors `is_staff` in PostHog, so every staff member has every permission and
    such a gate would let everyone in.
    """

    # Who passes, shown next to the disabled button so staff know whom to ask, for example
    # "members of the Billing Team group".
    label: str
    check: Callable[["HttpRequest"], bool]
    # Set by Gate.owner(). The shell replaces the gate with the staff group of the panel or tool owner.
    from_owner: bool = False

    @staticmethod
    def group(name: str) -> "Gate":
        return Gate(
            label=f"members of the {name} group",
            check=lambda request: request.user.groups.filter(name=name).exists(),
        )

    @staticmethod
    def owner() -> "Gate":
        return Gate(label="members of the owning team's staff group", check=_unresolved_owner_gate, from_owner=True)

    def resolve(self, owner: Owner) -> "Gate":
        if not self.from_owner:
            return self
        if owner.staff_group is None:
            raise ValueError(
                f"An operation of {owner.name} uses Gate.owner(), but Owner {owner.name!r} has no staff_group. "
                "Set staff_group on the Owner to the Django group whose members may run it."
            )
        return Gate.group(owner.staff_group)

    def allows(self, request: "HttpRequest") -> bool:
        return self.check(request)


def check_danger(key: str, danger: bool, form_class: type[forms.Form] | None, undo_hint: str) -> None:
    # The console writes the reason to the audit log, so nobody runs a destructive action without saying why.
    if danger and (form_class is None or "reason" not in form_class.base_fields):
        raise ValueError(f"Danger operation {key!r} needs a form with a reason field")
    if danger and not undo_hint.strip():
        raise ValueError(
            f"Danger operation {key!r} needs an undo_hint that says how to undo it, or that it cannot be undone"
        )


class OperationHandler(Protocol):
    """Returns None when done. To report a failure, add an error message and return a 4xx or 5xx response.

    It may return a `Page` instead, which the console shows once as the result, for example a password that
    staff must copy now in a `Secret` block.
    """

    def __call__(
        self, request: "HttpRequest", obj: "Model", form: forms.Form | None
    ) -> "HttpResponse | Page | None": ...


class RecordPreviewHandler(Protocol):
    """Shows what an operation would change on the record before it runs, as a `Page`. It must not change anything.

    To refuse the input, add an error to the form; the console then shows the form again.
    """

    def __call__(self, request: "HttpRequest", obj: "Model", form: forms.Form) -> "Page": ...


@frozen
class Operation:
    """An action on a record. The handler returns None when it is done, and the console sends staff back to the record.

    An operation with a form gets its own form page. Without a form it runs from a button in the panel.
    """

    key: str
    label: str
    handler: OperationHandler
    danger: bool = False
    form_class: type[forms.Form] | None = None
    # Starting values for the form, usually the record's current state, so an unchanged submit changes nothing.
    form_initial: dict[str, object] | None = None
    description: str = ""
    undo_hint: str = ""
    gate: Gate | None = None
    # Staff confirm on a page that shows what will change, for an action that is hard to take back.
    preview: RecordPreviewHandler | None = None

    def __post_init__(self) -> None:
        check_danger(self.key, self.danger, self.form_class, self.undo_hint)
        if self.preview is not None and self.form_class is None:
            raise ValueError(f"Operation {self.key!r} has a preview, so it needs a form for the preview to read")


class ReasonForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")


class Panel:
    """One card on a record page. Subclass it in `<app>/console.py` and register it with `console.register_panel`.

    A panel returns data (facts and operations). The console renders it, so panels need no templates.
    Read posthog/admin/console/AGENTS.md before you add one.
    """

    record: ClassVar[str]
    key: ClassVar[str]
    title: ClassVar[str]
    owner: ClassVar[Owner]
    danger: ClassVar[bool] = False
    # A page sorts its panels by order, then by title. Core panels set an order below the default, so they lead.
    order: ClassVar[int] = 100
    # Every operation key that operations() can return, in any state. An old URL can point at an operation form only
    # on a panel that declares its keys, and the console refuses to show an operation whose key is not declared.
    operation_keys: ClassVar[frozenset[str] | None] = None

    def facts(self, obj: "Model") -> list[Fact]:
        return []

    def operations(self, obj: "Model") -> list[Operation]:
        return []
