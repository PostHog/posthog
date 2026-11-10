import ast
from datetime import UTC, datetime
from typing import Any, ClassVar

from django import forms
from django.http import QueryDict
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from posthog.models.data_deletion_request import DataDeletionRequest, RequestType

# Types staff do not create by hand. An existing request of one of these types keeps its own type selectable.
UNSUPPORTED_REQUEST_TYPES = (
    RequestType.HOGQL_EVENT_REMOVAL,
    RequestType.PERSON_REMOVAL,
    RequestType.PROPERTY_REMOVAL,
)

CLICKHOUSE_TEAM_REQUEST_TYPES = (RequestType.PROPERTY_REMOVAL,)

DATETIME_FIELDS = ("start_time", "end_time")
DATETIME_HELP = "In UTC, for example 2026-01-31 23:59."


def _parse_list(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            parsed = None
        if isinstance(parsed, list | tuple):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [line.strip() for line in text.split("\n") if line.strip()]


class ArrayTextareaField(forms.CharField):
    widget = forms.Textarea

    def prepare_value(self, value: Any) -> Any:
        if isinstance(value, list):
            return "\n".join(str(item) for item in value)
        return value

    def clean(self, value: Any) -> list[str]:
        return _parse_list(super().clean(value) or "")

    def has_changed(self, initial: Any, data: Any) -> bool:
        # The initial value is a list and the submitted one is text, so compare them parsed.
        initial_list = [str(item) for item in initial] if isinstance(initial, list) else _parse_list(initial or "")
        return initial_list != _parse_list(data or "")


class UTCDateTimeField(forms.DateTimeField):
    def prepare_value(self, value: Any) -> Any:
        # The console template prints the value as is, and a datetime would print in the localized long format.
        if isinstance(value, datetime):
            return value.astimezone(UTC).replace(tzinfo=None).isoformat(sep=" ")
        return value


def _choice_label(value: str, label: str) -> str:
    return label if label.startswith("HogQL") else label.capitalize()


# The console types operation forms as forms.Form, so the ModelForm also derives from it. Form adds nothing to
# BaseForm, so this changes no behavior.
class DataDeletionRequestForm(forms.ModelForm, forms.Form):
    events = ArrayTextareaField(
        required=False,
        help_text="One event name per line. Leave it empty only when every event is matched.",
    )
    properties = ArrayTextareaField(
        required=False,
        help_text="One property name per line. A property removal needs a property or a person property.",
    )
    person_properties = ArrayTextareaField(
        required=False,
        label="Person properties",
        help_text="One property name per line, removed from the person properties stored on each event.",
    )
    start_time = UTCDateTimeField(required=False, label="Start time", help_text=DATETIME_HELP)
    end_time = UTCDateTimeField(required=False, label="End time", help_text=DATETIME_HELP)
    hogql_predicate = forms.CharField(
        required=False,
        label="HogQL filter",
        widget=forms.Textarea,
        help_text="Optional. A HogQL condition on the events table, combined with the other filters. "
        "For example: properties.$browser = 'Chrome'.",
    )

    # The request's updated_at when staff opened the form. The edit lands only if nothing changed since.
    revision = forms.CharField(required=False, widget=forms.HiddenInput)

    offer_clickhouse_team_types: ClassVar[bool] = False
    # Set by for_request, because the console builds an operation's form without an instance.
    bound_instance: ClassVar[DataDeletionRequest | None] = None

    class Meta:
        model = DataDeletionRequest
        fields = (
            "team_id",
            "request_type",
            "start_time",
            "end_time",
            "events",
            "delete_all_events",
            "properties",
            "person_properties",
            "hogql_predicate",
            "notes",
        )
        labels = {
            "team_id": "Team ID",
            "request_type": "Type",
            "delete_all_events": "Match every event in the time range",
        }
        help_texts = {
            "request_type": "Event removal deletes whole events. Property removal removes properties from them.",
            "delete_all_events": "Leave the events empty when you set this.",
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if self.bound_instance is not None:
            kwargs.setdefault("instance", self.bound_instance)
        super().__init__(*args, **kwargs)
        self.original_request_type: str | None = None
        if self.instance._state.adding:
            del self.fields["revision"]
        else:
            self.original_request_type = self.instance.request_type
            del self.fields["team_id"]
            updated_at = self.instance.updated_at
            self.fields["revision"].initial = updated_at.isoformat() if updated_at else ""
        hidden_types = set(UNSUPPORTED_REQUEST_TYPES)
        if self.offer_clickhouse_team_types:
            hidden_types -= set(CLICKHOUSE_TEAM_REQUEST_TYPES)
        request_type = self.fields["request_type"]
        assert isinstance(request_type, forms.ChoiceField)
        request_type.choices = [
            (value, _choice_label(value, label))
            for value, label in RequestType.choices
            if value not in hidden_types or value == self.original_request_type
        ]

    def needs_clickhouse_team(self) -> bool:
        chosen = self.cleaned_data.get("request_type")
        return chosen in CLICKHOUSE_TEAM_REQUEST_TYPES and chosen != self.original_request_type

    @classmethod
    def for_staff(cls, offer_clickhouse_team_types: bool) -> type["DataDeletionRequestForm"]:
        return type("DataDeletionRequestForm", (cls,), {"offer_clickhouse_team_types": offer_clickhouse_team_types})

    @classmethod
    def for_request(cls, obj: DataDeletionRequest) -> type["DataDeletionRequestForm"]:
        # Record operations build their form without the request, so every type ClickHouse Team members may pick
        # is offered here, and the handler refuses it for everyone else.
        return type("DataDeletionRequestForm", (cls,), {"offer_clickhouse_team_types": True, "bound_instance": obj})


def initial_from_query(query: QueryDict) -> dict[str, object]:
    initial: dict[str, object] = dict(query.items())
    # Read naive values as UTC, and drop values that do not parse, so a bad link still opens the form.
    for field in DATETIME_FIELDS:
        value = initial.get(field)
        if not isinstance(value, str):
            continue
        try:
            parsed = parse_datetime(value)
        except ValueError:
            parsed = None
        if parsed is None:
            initial.pop(field)
        elif timezone.is_naive(parsed):
            initial[field] = timezone.make_aware(parsed, UTC)
        else:
            initial[field] = parsed
    return initial
