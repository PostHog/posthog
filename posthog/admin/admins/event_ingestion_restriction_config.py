from django import forms
from django.contrib import admin

from posthog.models.event_ingestion_restriction_config import (
    INGESTION_PIPELINES,
    EventIngestionRestrictionConfig,
    RestrictionType,
)


class EventIngestionRestrictionConfigForm(forms.ModelForm):
    # Multi-select field for pipelines with checkboxes
    pipelines = forms.MultipleChoiceField(
        required=True,
        widget=forms.CheckboxSelectMultiple,
        choices=[(p["value"], p["label"]) for p in INGESTION_PIPELINES],
        help_text="Select which ingestion pipelines this restriction applies to (at least one required)",
        error_messages={"required": "Please select at least one pipeline"},
    )

    # Friendly field shown instead of raw JSON args
    topic = forms.CharField(
        required=False,
        help_text="Kafka topic to redirect events to. Only used for 'Redirect To Topic' restriction type.",
    )

    class Meta:
        model = EventIngestionRestrictionConfig
        fields = [
            "token",
            "restriction_type",
            "topic",
            "note",
            "pipelines",
            "distinct_ids",
            "session_ids",
            "event_names",
            "event_uuids",
        ]
        help_texts = {
            "distinct_ids": (
                "Optional: List of specific distinct IDs to restrict. "
                "Empty = matches all distinct IDs. "
                "Multiple values = matches if distinct_id is ANY of them (OR within field). "
                "Combined with other filters using AND logic."
            ),
            "session_ids": (
                "Optional: List of specific session IDs to restrict. "
                "Empty = matches all session IDs. "
                "Multiple values = matches if session_id is ANY of them (OR within field). "
                "Combined with other filters using AND logic."
            ),
            "event_names": (
                "Optional: List of specific event names to restrict (e.g., '$pageview', '$autocapture'). "
                "Empty = matches all event names. "
                "Multiple values = matches if event name is ANY of them (OR within field). "
                "Combined with other filters using AND logic."
            ),
            "event_uuids": (
                "Optional: List of specific event UUIDs to restrict. "
                "Empty = matches all event UUIDs. "
                "Multiple values = matches if event UUID is ANY of them (OR within field). "
                "Combined with other filters using AND logic."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Populate topic from args on edit
        if self.instance and self.instance.pk and isinstance(self.instance.args, dict):
            self.fields["topic"].initial = self.instance.args.get("topic", "")

    def clean(self):
        cleaned_data = super().clean() or {}
        restriction_type = cleaned_data.get("restriction_type")
        topic = cleaned_data.get("topic", "").strip()

        if restriction_type == RestrictionType.REDIRECT_TO_TOPIC:
            if not topic:
                self.add_error("topic", "Topic is required for 'Redirect To Topic' restriction type.")
            else:
                self.instance.args = {"topic": topic}
        else:
            self.instance.args = None

        return cleaned_data


class EventIngestionRestrictionConfigAdmin(admin.ModelAdmin):
    form = EventIngestionRestrictionConfigForm
    list_display = (
        "id",
        "token",
        "restriction_type",
        "pipelines",
        "display_topic",
        "has_distinct_ids",
        "has_session_ids",
        "has_event_names",
        "has_event_uuids",
    )
    list_filter = ("restriction_type",)
    search_fields = ("token", "distinct_ids", "session_ids", "event_names", "event_uuids")

    @admin.display(description="Topic")
    def display_topic(self, obj):
        if isinstance(obj.args, dict):
            return obj.args.get("topic", "")
        return ""

    @admin.display(boolean=True, description="Has Distinct IDs")
    def has_distinct_ids(self, obj):
        return bool(obj.distinct_ids)

    @admin.display(boolean=True, description="Has Session IDs")
    def has_session_ids(self, obj):
        return bool(obj.session_ids)

    @admin.display(boolean=True, description="Has Event Names")
    def has_event_names(self, obj):
        return bool(obj.event_names)

    @admin.display(boolean=True, description="Has Event UUIDs")
    def has_event_uuids(self, obj):
        return bool(obj.event_uuids)

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change, **kwargs)
        restriction_type_field = form.base_fields.get("restriction_type")
        if restriction_type_field:
            restriction_type_field.help_text = (
                f"{RestrictionType.SKIP_PERSON_PROCESSING.label}: Skip person processing for specified filters. "
                f"{RestrictionType.DROP_EVENT_FROM_INGESTION.label}: Drop events from ingestion for specified filters. "
                f"{RestrictionType.FORCE_OVERFLOW_FROM_INGESTION.label}: Force overflow from ingestion for specified filters. "
                f"{RestrictionType.REDIRECT_TO_DLQ.label}: Redirect events to dead letter queue for specified filters. "
                f"{RestrictionType.REDIRECT_TO_TOPIC.label}: Redirect events to a custom Kafka topic (enter topic name below)."
            )

        return form
