from django.db import models
from django.db.models.signals import post_save, post_delete

from posthog.models import Action
from posthog.models.signals import mutable_receiver
from posthog.models.utils import UUIDModel
from django.contrib.postgres.fields import ArrayField
from dateutil.rrule import rrule, DAILY
from django.db.models.signals import pre_save
from django.dispatch import receiver


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
    internal_targeting_flag: models.ForeignKey = models.ForeignKey(
        "posthog.FeatureFlag",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="surveys_internal_targeting_flag",
        related_query_name="survey_internal_targeting_flag",
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
    # It's not a strict limit as it's enforced in a periodic task
    responses_limit = models.PositiveIntegerField(null=True)

    iteration_count = models.PositiveIntegerField(null=True)
    iteration_frequency_days = models.PositiveIntegerField(null=True)
    iteration_start_dates = ArrayField(
        base_field=models.DateTimeField(null=True),
        blank=True,
        default=None,
        null=True,
        size=None,
    )
    current_iteration = models.PositiveIntegerField(null=True)
    current_iteration_start_date = models.DateTimeField(null=True)
    actions = models.ManyToManyField(Action)


@receiver(pre_save, sender=Survey)
def update_survey_iterations(sender, instance, *args, **kwargs):
    iteration_count = 0 if instance.iteration_count is None else instance.iteration_count
    iteration_frequency_dates = 0 if instance.iteration_frequency_days is None else instance.iteration_frequency_days

    if instance.iteration_count == 0 or instance.iteration_frequency_days == 0:
        instance.iteration_start_dates = []
        instance.current_iteration = None
        instance.current_iteration_start_date = None
        return

    if instance.start_date is None:
        instance.iteration_start_dates = None
        return

    instance.iteration_start_dates = list(
        rrule(
            DAILY,
            count=iteration_count,
            interval=iteration_frequency_dates,
            dtstart=instance.start_date,
        )
    )

    if iteration_count > 0 and (instance.current_iteration is None or instance.current_iteration == 0):
        instance.current_iteration = 1
        instance.current_iteration_start_date = instance.start_date


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
