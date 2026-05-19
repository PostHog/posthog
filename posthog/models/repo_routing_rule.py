from django.conf import settings
from django.db import models

from posthog.models.utils import UUIDModel


class RepoRoutingRule(UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="repo_routing_rules")
    rule_text = models.TextField()
    repository = models.CharField(max_length=255)
    priority = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "id"]
        indexes = [
            models.Index(fields=["team", "priority"], name="idx_repo_routing_rule_team"),
        ]
