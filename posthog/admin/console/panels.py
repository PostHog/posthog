from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Protocol

from django import forms
from django.utils.safestring import SafeData

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from django.db.models import Model
    from django.http import HttpRequest, HttpResponse


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
        if self.href is not None and (not self.href.startswith("/") or self.href.startswith("//")):
            raise ValueError(f"Fact {self.label!r} links to {self.href!r}. Link to a PostHog path that starts with /.")


def check_danger(key: str, danger: bool, form_class: type[forms.Form] | None, undo_hint: str) -> None:
    # The console writes the reason to the audit log, so nobody runs a destructive action without saying why.
    if danger and (form_class is None or "reason" not in form_class.base_fields):
        raise ValueError(f"Danger operation {key!r} needs a form with a reason field")
    if danger and not undo_hint.strip():
        raise ValueError(
            f"Danger operation {key!r} needs an undo_hint that says how to undo it, or that it cannot be undone"
        )


class OperationHandler(Protocol):
    """Returns None when done. To report a failure, add an error message and return a 4xx or 5xx response."""

    def __call__(self, request: "HttpRequest", obj: "Model", form: forms.Form | None) -> "HttpResponse | None": ...


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

    def __post_init__(self) -> None:
        check_danger(self.key, self.danger, self.form_class, self.undo_hint)


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

    def facts(self, obj: "Model") -> list[Fact]:
        return []

    def operations(self, obj: "Model") -> list[Operation]:
        return []
