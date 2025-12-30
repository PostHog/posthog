from decimal import Decimal

from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from posthog.models.team.team import Team
from posthog.models.utils import RootTeamMixin, UUIDTModel


class SdkPolicyConfig(UUIDTModel, RootTeamMixin):
    class MatchType(models.TextChoices):
        ALL = "all"
        ANY = "any"

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    match_type = models.CharField(
        max_length=24, choices=MatchType.choices, null=False, blank=False, default=MatchType.ALL
    )

    sample_rate = models.DecimalField(
        # will store a decimal between 0 and 1 allowing up to 2 decimal places
        max_digits=3,
        decimal_places=2,
        null=False,
        blank=False,
        default=Decimal(1),
        validators=[MinValueValidator(Decimal(0)), MaxValueValidator(Decimal(1))],
    )
    minimum_duration_milliseconds = models.IntegerField(
        default=None, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(30000)]
    )
    linked_feature_flag = models.JSONField(null=True, blank=True)
    event_triggers = ArrayField(models.TextField(null=True, blank=True), default=list, blank=True, null=True)
    url_triggers = ArrayField(models.JSONField(null=True, blank=True), default=list, blank=True, null=True)
    url_blocklist = ArrayField(models.JSONField(null=True, blank=True), default=list, blank=True, null=True)


class SdkPolicyConfigAssignment(UUIDTModel, RootTeamMixin):
    class Context(models.TextChoices):
        ERROR_TRACKING = "error-tracking"

    class Library(models.TextChoices):
        WEB = "web"

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    config = models.ForeignKey("SdkPolicyConfig", on_delete=models.CASCADE, related_name="assignments")
    context = models.CharField(max_length=24, choices=Context.choices, null=False, blank=False)
    # None value applies to libraries without a specific assignment
    library = models.CharField(max_length=24, choices=Library.choices, null=True, blank=True, default=None)

    class Meta:
        unique_together = ("team", "context", "library")


def get_policy_config(
    team: Team, context: SdkPolicyConfigAssignment.Context, library: SdkPolicyConfigAssignment.Library | None
) -> dict | None:
    return (
        SdkPolicyConfig.objects.filter(
            team=team, assignments__isnull=False, assignments__context=context, assignments__library=library
        )
        .values()
        .first()
    )
