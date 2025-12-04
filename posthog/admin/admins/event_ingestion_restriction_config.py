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

    class Meta:
        model = EventIngestionRestrictionConfig
        fields = ["token", "restriction_type", "note", "pipelines", "distinct_ids", "session_ids"]
        help_texts = {
            "distinct_ids": (
                "Optional: Comma-separated list of specific distinct IDs to restrict. "
                "If both distinct_ids and session_ids are empty, restriction applies to ALL events for this token. "
                "If either field has values, restriction applies when the event matches ANY of the specified distinct IDs OR session IDs."
            ),
            "session_ids": (
                "Optional: Comma-separated list of specific session IDs to restrict. "
                "If both distinct_ids and session_ids are empty, restriction applies to ALL events for this token. "
                "If either field has values, restriction applies when the event matches ANY of the specified distinct IDs OR session IDs."
            ),
        }


class EventIngestionRestrictionConfigAdmin(admin.ModelAdmin):
    form = EventIngestionRestrictionConfigForm
    list_display = ("id", "token", "restriction_type", "pipelines", "has_distinct_ids", "has_session_ids")
    list_filter = ("restriction_type",)
    search_fields = ("token", "distinct_ids", "session_ids")

    @admin.display(boolean=True, description="Has Distinct IDs")
    def has_distinct_ids(self, obj):
        return bool(obj.distinct_ids)

    @admin.display(boolean=True, description="Has Session IDs")
    def has_session_ids(self, obj):
        return bool(obj.session_ids)

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change, **kwargs)
        restriction_type_field = form.base_fields.get("restriction_type")
        if restriction_type_field:
            restriction_type_field.help_text = (
                f"{RestrictionType.SKIP_PERSON_PROCESSING.label}: Skip person processing for specified tokens/distinct IDs/session IDs. "
                f"{RestrictionType.DROP_EVENT_FROM_INGESTION.label}: Drop events from ingestion for specified tokens/distinct IDs/session IDs. "
                f"{RestrictionType.FORCE_OVERFLOW_FROM_INGESTION.label}: Force overflow from ingestion for specified tokens/distinct IDs/session IDs."
            )

        return form
