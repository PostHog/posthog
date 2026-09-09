from django.conf import settings
from django.db import models

from posthog.models.utils import UUIDModel


class RepoRoutingRule(UUIDModel):
    # Every add path rejects longer text, so the stored rule always equals what `prompt_text`
    # renders into agent prompts. `rule_text` stays a TextField because a DB-level cap would
    # turn an over-long rule into an opaque error instead of a Slack reply.
    MAX_RULE_TEXT_LENGTH = 300

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="repo_routing_rules")
    rule_text = models.TextField()
    repository = models.CharField(max_length=255)
    priority = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def prompt_text(self) -> str:
        """Whitespace-flattened rule text for prompt rendering.

        The cap is a backstop for rows written before the add paths enforced
        MAX_RULE_TEXT_LENGTH, so one verbose legacy rule cannot dominate a prompt.
        """
        return " ".join(self.rule_text.split())[: self.MAX_RULE_TEXT_LENGTH]

    class Meta:
        ordering = ["priority", "id"]
        indexes = [
            models.Index(fields=["team", "priority"], name="idx_repo_routing_rule_team"),
        ]
