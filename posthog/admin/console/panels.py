from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Protocol

from django import forms

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


@frozen
class Fact:
    label: str
    value: str
    tone: Tone | None = None
    mono: bool = False


class OperationHandler(Protocol):
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
    description: str = ""

    def __post_init__(self) -> None:
        # The console writes the reason to the audit log, so nobody runs a destructive action without saying why.
        if self.danger and (self.form_class is None or "reason" not in self.form_class.base_fields):
            raise ValueError(f"Danger operation {self.key!r} needs a form with a reason field")


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
