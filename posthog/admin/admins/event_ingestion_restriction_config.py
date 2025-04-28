from django.contrib import admin
from django.contrib import messages
from posthog.models.event_ingestion_restriction_config import EventIngestionRestrictionConfig, RestrictionType


@admin.register(EventIngestionRestrictionConfig)
class EventIngestionRestrictionConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "token", "restriction_type", "has_distinct_ids")
    list_filter = ("restriction_type",)
    search_fields = ("token", "distinct_ids")
    readonly_fields = ("id", "created_at")
    fieldsets = (
        (None, {"fields": ("token", "restriction_type")}),
        (
            "Distinct IDs",
            {
                "fields": ("distinct_ids",),
                "description": "Optional list of distinct IDs. If not provided, the token itself will be used.",
            },
        ),
        (
            "Metadata",
            {
                "fields": ("id", "created_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def has_distinct_ids(self, obj):
        return bool(obj.distinct_ids)

    has_distinct_ids.boolean = True
    has_distinct_ids.short_description = "Has Distinct IDs"

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        restriction_type_field = form.base_fields.get("restriction_type")
        if restriction_type_field:
            restriction_type_field.help_text = (
                f"{RestrictionType.SKIP_PERSON_PROCESSING.label}: Skip person processing for specified tokens/distinct IDs. "
                f"{RestrictionType.DROP_EVENTS_FROM_INGESTION.label}: Drop events from ingestion for specified tokens/distinct IDs. "
                f"{RestrictionType.FORCE_OVERFLOW_FROM_INGESTION.label}: Force overflow from ingestion for specified tokens/distinct IDs."
            )

        return form

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return (*self.readonly_fields, "token", "restriction_type", "distinct_ids")
        return self.readonly_fields

    def change_view(self, request, object_id, form_url="", extra_context=None):
        messages.warning(
            request,
            "Editing existing configs is not supported. Please delete this configuration and create a new one if you need to make changes.",
        )
        return super().change_view(request, object_id, form_url, extra_context)
