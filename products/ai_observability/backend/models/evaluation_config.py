from django.db import models


class EvaluationConfig(models.Model):
    """Team-level configuration for evaluations"""

    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="evaluation_config",
    )

    # Active BYOK key (single source of truth)
    active_provider_key = models.ForeignKey(
        "ai_observability.LLMProviderKey",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "llm_analytics_evaluationconfig"

    def __str__(self):
        return f"EvaluationConfig for team {self.team_id}"
