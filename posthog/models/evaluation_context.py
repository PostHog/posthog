from django.db import models

from posthog.models.utils import UUIDModel


def normalize_context_name(name: str) -> str:
    """Normalize an evaluation context name for storage and comparison.

    Context names are case-insensitive and whitespace-trimmed.
    """
    return name.strip().lower()


class EvaluationContext(UUIDModel):
    """
    A named evaluation context scoped to a team.

    Evaluation contexts control where feature flags evaluate at runtime
    (e.g. "production", "staging", "docs-page"). They are independent
    from organizational tags — creating, renaming, or deleting a context
    never affects a flag's tags, and vice versa.

    SDK clients send matching context names in their flag evaluation
    requests; flags only evaluate when the request contexts match.
    """

    name = models.CharField(max_length=255)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="evaluation_context_set")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [["team", "name"]]

    def __str__(self) -> str:
        return f"{self.team_id}:{self.name}"


class FeatureFlagEvaluationContext(UUIDModel):
    """
    Links a feature flag to an evaluation context.

    When a flag has evaluation contexts, it will only evaluate when
    the SDK/client provides matching context names.
    """

    feature_flag = models.ForeignKey(
        "posthog.FeatureFlag", on_delete=models.CASCADE, related_name="flag_evaluation_contexts"
    )
    evaluation_context = models.ForeignKey(
        "posthog.EvaluationContext", on_delete=models.CASCADE, related_name="feature_flags"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [["feature_flag", "evaluation_context"]]

    def __str__(self) -> str:
        return f"{self.feature_flag.key} - {self.evaluation_context.name}"


class TeamDefaultEvaluationContext(UUIDModel):
    """
    Defines default evaluation contexts automatically applied to new feature flags in a team.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="default_evaluation_context_set")
    evaluation_context = models.ForeignKey(
        "posthog.EvaluationContext", on_delete=models.CASCADE, related_name="team_defaults"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [["team", "evaluation_context"]]

    def __str__(self) -> str:
        return f"{self.team.name} - {self.evaluation_context.name}"
