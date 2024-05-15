from django.db import models

from posthog.models.utils import UUIDModel
from posthog.utils import generate_short_id


class ReferralProgram(UUIDModel):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "short_id"], name="unique short_id for team")]

    short_id: models.CharField = models.CharField(max_length=12, blank=True, default=generate_short_id)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    team: models.ForeignKey = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="referral_codes",
        related_query_name="referral_code",
    )
    max_total_redemption_count: models.PositiveIntegerField = models.PositiveIntegerField(null=True, blank=True)
    max_redemption_count_per_referrer: models.PositiveIntegerField = models.PositiveIntegerField(null=True, blank=True)
