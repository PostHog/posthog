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
        fields = ["token", "restriction_type", "note", "pipelines", "distinct_ids"]


class EventIngestionRestrictionConfigAdmin(admin.ModelAdmin):
    form = EventIngestionRestrictionConfigForm
    list_display = ("id", "token", "restriction_type", "pipelines", "has_distinct_ids")
    list_filter = ("restriction_type",)
    search_fields = ("token", "distinct_ids")

    @admin.display(boolean=True, description="Has Distinct IDs")
    def has_distinct_ids(self, obj):
        return bool(obj.distinct_ids)

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change, **kwargs)
        restriction_type_field = form.base_fields.get("restriction_type")
        if restriction_type_field:
            restriction_type_field.help_text = (
                f"{RestrictionType.SKIP_PERSON_PROCESSING.label}: Skip person processing for specified tokens/distinct IDs. "
                f"{RestrictionType.DROP_EVENT_FROM_INGESTION.label}: Drop events from ingestion for specified tokens/distinct IDs. "
                f"{RestrictionType.FORCE_OVERFLOW_FROM_INGESTION.label}: Force overflow from ingestion for specified tokens/distinct IDs."
            )

        return form
