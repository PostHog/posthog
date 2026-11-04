from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Protocol

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
    # Slug of a mini crest from @posthog/brand, for example "workflows". The build copies every crest.
    crest: str


@frozen
class Fact:
    label: str
    value: str
    tone: Tone | None = None
    mono: bool = False


@frozen
class OperationField:
    name: str
    label: str
    help_text: str = ""
    required: bool = True


class OperationHandler(Protocol):
    def __call__(self, request: "HttpRequest", obj: "Model") -> "HttpResponse": ...


@frozen
class Operation:
    key: str
    label: str
    handler: OperationHandler
    danger: bool = False
    fields: tuple[OperationField, ...] = ()
    description: str = ""


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
