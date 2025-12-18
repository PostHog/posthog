from decimal import Decimal

from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from posthog.models.utils import RootTeamMixin, UUIDTModel


class SdkPolicyConfig(UUIDTModel, RootTeamMixin):
    class MatchType(models.TextChoices):
        AND = "and", "AND"
        OR = "or", "OR"

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    match_type = models.CharField(
        max_length=24, choices=MatchType.choices, null=False, blank=False, default=MatchType.AND
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
    events_trigger = ArrayField(models.TextField(null=True, blank=True), default=list, blank=True, null=True)
    url_trigger = ArrayField(models.JSONField(null=True, blank=True), default=list, blank=True, null=True)
    url_blocklist = ArrayField(models.JSONField(null=True, blank=True), default=list, blank=True, null=True)
