from django.contrib import admin
from django.db.models import OuterRef, Subquery

from posthog.models.global_rate_limit_threshold_config import GlobalRateLimitThresholdConfig


@admin.register(GlobalRateLimitThresholdConfig)
class GlobalRateLimitThresholdConfigAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "token",
        "display_team_id",
        "distinct_id",
        "threshold",
        "display_resolved_key",
        "note",
        "updated_at",
    )
    list_per_page = 20
    readonly_fields = ("display_team_id", "display_resolved_key", "created_at", "updated_at")
    search_fields = ("token", "distinct_id", "note")
    fields = (
        "token",
        "distinct_id",
        "threshold",
        "note",
        "display_team_id",
        "display_resolved_key",
        "created_at",
        "updated_at",
    )

    def get_queryset(self, request):
        from posthog.models.team.team import Team

        qs = super().get_queryset(request)
        return qs.annotate(
            team_id_from_token=Subquery(Team.objects.filter(api_token=OuterRef("token")).values("id")[:1])
        )

    @admin.display(description="Team ID")
    def display_team_id(self, obj):
        return getattr(obj, "team_id_from_token", None)

    @admin.display(description="Resolved key")
    def display_resolved_key(self, obj):
        return obj.resolved_key
