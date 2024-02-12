from django.db import models
from django.db.models.signals import post_save, post_delete
from posthog.models.signals import mutable_receiver
from posthog.models.utils import UUIDModel


class Survey(UUIDModel):
    class SurveyType(models.TextChoices):
        POPOVER = "popover", "popover"
        WIDGET = "widget", "widget"
        BUTTON = "button", "button"
        EMAIL = "email", "email"
        FULL_SCREEN = "full_screen", "full screen"
        API = "api", "api"

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "name"], name="unique survey name for team")]

    team: models.ForeignKey = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="surveys",
        related_query_name="survey",
    )
    name: models.CharField = models.CharField(max_length=400)
    description: models.TextField = models.TextField(blank=True)
    linked_flag: models.ForeignKey = models.ForeignKey(
        "posthog.FeatureFlag",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="surveys_linked_flag",
        related_query_name="survey_linked_flag",
    )
    targeting_flag: models.ForeignKey = models.ForeignKey(
        "posthog.FeatureFlag",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="surveys_targeting_flag",
        related_query_name="survey_targeting_flag",
    )
    type: models.CharField = models.CharField(max_length=40, choices=SurveyType.choices)
    conditions: models.JSONField = models.JSONField(blank=True, null=True)
    questions: models.JSONField = models.JSONField(blank=True, null=True)
    appearance: models.JSONField = models.JSONField(blank=True, null=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    created_by: models.ForeignKey = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        related_name="surveys",
        related_query_name="survey",
        null=True,
    )
    start_date: models.DateTimeField = models.DateTimeField(null=True)
    end_date: models.DateTimeField = models.DateTimeField(null=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    archived: models.BooleanField = models.BooleanField(default=False)


@mutable_receiver([post_save, post_delete], sender=Survey)
def update_surveys_opt_in(sender, instance, **kwargs):
    active_surveys_count = (
        Survey.objects.filter(
            team_id=instance.team_id,
            start_date__isnull=False,
            end_date__isnull=True,
            archived=False,
        )
        .exclude(type="api")
        .count()
    )

    if active_surveys_count > 0 and not instance.team.surveys_opt_in:
        instance.team.surveys_opt_in = True
        instance.team.save(update_fields=["surveys_opt_in"])
    elif active_surveys_count == 0 and instance.team.surveys_opt_in is True:
        instance.team.surveys_opt_in = False
        instance.team.save(update_fields=["surveys_opt_in"])
