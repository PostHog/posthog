from django.contrib import admin

from posthog.models.event_ingestion_restriction_config import RestrictionType


class EventIngestionRestrictionConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "token", "restriction_type", "has_distinct_ids")
    list_filter = ("restriction_type",)
    search_fields = ("token", "distinct_ids")
    fieldsets = (
        (None, {"fields": ("token", "restriction_type", "note")}),
        (
            "Distinct IDs",
            {
                "fields": ("distinct_ids",),
                "description": "Optional list of distinct IDs. If not provided, the token itself will be used.",
            },
        ),
    )

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
