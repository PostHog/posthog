from django.contrib import admin
from posthog.models.token_restriction_config import TokenRestrictionConfig, RestrictionType


@admin.register(TokenRestrictionConfig)
class TokenRestrictionConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "token", "restriction_type", "has_distinct_ids", "enabled")
    list_filter = ("restriction_type", "enabled")
    search_fields = ("token", "distinct_ids")
    readonly_fields = ("id", "created_at")
    fieldsets = (
        (None, {"fields": ("token", "restriction_type", "enabled")}),
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

        enabled_field = form.base_fields.get("enabled")
        if enabled_field:
            enabled_field.help_text = (
                "When disabled, the restriction will not be applied and the Redis key will be deleted."
            )

        return form
