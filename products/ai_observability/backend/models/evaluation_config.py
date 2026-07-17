from django.db import models
from django.utils import timezone

from products.ai_observability.backend.constants import trial_eval_deprecation_date


class EvaluationConfig(models.Model):
    """Team-level configuration and usage tracking for evaluations"""

    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="evaluation_config",
    )

    # Trial evaluations (permanent limit for alpha)
    trial_eval_limit = models.IntegerField(default=100)
    trial_evals_used = models.IntegerField(default=0)

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

    @property
    def trial_evals_remaining(self) -> int:
        return max(0, self.trial_eval_limit - self.trial_evals_used)

    @property
    def is_trial_grandfathered(self) -> bool:
        """Only teams already mid-trial keep PostHog-funded inference, and only until the cutoff.
        Teams that never started (used == 0) or exhausted (used >= limit) the trial are terminal
        and must bring their own provider key — as are all teams once the deprecation date passes.
        """
        return 0 < self.trial_evals_used < self.trial_eval_limit and timezone.now() < trial_eval_deprecation_date()
