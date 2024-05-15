from django.db import models

from posthog.models.utils import UUIDModel
from posthog.utils import generate_short_id


class ReferralProgramReferrer(UUIDModel):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user_id", "referral_program"], name="unique user_id for program referrer")
        ]

    user_id: models.CharField = models.CharField(max_length=128)
    code: models.TextField = models.TextField(max_length=128, default=generate_short_id)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    referral_program: models.ForeignKey = models.ForeignKey(
        "ReferralProgram",
        on_delete=models.CASCADE,
        related_name="referrer",
        related_query_name="referrers",
    )
    max_redemption_count: models.PositiveIntegerField = models.PositiveIntegerField(null=True, blank=True)
