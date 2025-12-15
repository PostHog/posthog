from django.db import models

from posthog.schema import QuickFilterType

from posthog.models.utils import UUIDModel


class QuickFilter(UUIDModel):
    TYPE_CHOICES = [(t.value, t.value) for t in QuickFilterType]

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    property_name = models.CharField(max_length=500)
    type = models.CharField(max_length=50, choices=TYPE_CHOICES, default=QuickFilterType.MANUAL_OPTIONS.value)
    options = models.JSONField(default=list, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_quickfilter"
        indexes = [
            models.Index(fields=["team"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} (Team: {self.team.name})"


class QuickFilterContext(UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    quick_filter = models.ForeignKey(QuickFilter, on_delete=models.CASCADE, related_name="context_memberships")
    context = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "context"]),
            models.Index(fields=["quick_filter", "context"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["team", "quick_filter", "context"], name="unique_filter_context")
        ]
        db_table = "posthog_quickfiltercontext"
