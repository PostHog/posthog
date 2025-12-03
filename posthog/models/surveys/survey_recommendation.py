from django.db import models

from posthog.models.utils import UUIDTModel


class SurveyRecommendation(UUIDTModel):
    """
    precomputed survey recommendations based on a team's posthog data.
    stores ready-to-create defaults for one-click launch.
    """

    class RecommendationType(models.TextChoices):
        LOW_CONVERSION_FUNNEL = "low_conversion_funnel", "Low conversion funnel"
        FEATURE_FLAG_FEEDBACK = "feature_flag_feedback", "Feature flag feedback"
        EXPERIMENT_FEEDBACK = "experiment_feedback", "Experiment feedback"
        DECLINING_FEATURE = "declining_feature", "Declining feature usage"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DISMISSED = "dismissed", "Dismissed"
        CONVERTED = "converted", "Converted to survey"

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="survey_recommendations",
    )

    recommendation_type = models.CharField(
        max_length=50,
        choices=RecommendationType.choices,
    )

    # recommendation source references
    source_insight = models.ForeignKey(
        "posthog.Insight",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    source_feature_flag = models.ForeignKey(
        "posthog.FeatureFlag",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    source_experiment = models.ForeignKey(
        "posthog.Experiment",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )

    # "ready-to-launch" survey payload for this recommendation
    survey_defaults = models.JSONField(
        help_text="""
        Ready-to-create survey payload:
        {
            "name": "Checkout Flow Feedback - abc123",
            "type": "popover",
            "questions": [{"type": "open", "question": "...", "optional": false}],
            "conditions": {"url": "...", "events": {...}},
            "appearance": {...},
            "linked_insight_id": 123,
        }
        """
    )

    # UI context
    display_context = models.JSONField(
        help_text="""
        Context for rendering the recommendation card:
        {
            "title": "Checkout Flow has 23% conversion",
            "description": "Ask users why they're dropping off at step 2",
            "metric_value": "23%",
            "source_name": "Checkout Flow",
        }
        """
    )

    # used for sorting recommendations
    score = models.FloatField(default=0.0)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    converted_survey = models.ForeignKey(
        "posthog.Survey",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="source_recommendation",
    )

    class Meta:
        indexes = [
            models.Index(fields=["team", "status"]),
            models.Index(fields=["team", "recommendation_type"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "recommendation_type", "source_insight"],
                condition=models.Q(source_insight__isnull=False),
                name="unique_insight_recommendation",
            ),
            models.UniqueConstraint(
                fields=["team", "recommendation_type", "source_feature_flag"],
                condition=models.Q(source_feature_flag__isnull=False),
                name="unique_flag_recommendation",
            ),
            models.UniqueConstraint(
                fields=["team", "recommendation_type", "source_experiment"],
                condition=models.Q(source_experiment__isnull=False),
                name="unique_experiment_recommendation",
            ),
        ]
