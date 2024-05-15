from django.db import models

from posthog.models.utils import UUIDModel


class ReferralProgramRedeemer(UUIDModel):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user_id", "referral_program"], name="unique user_id for program redeemer")
        ]

    user_id: models.CharField = models.CharField(max_length=128)
    referrer: models.ForeignKey = models.ForeignKey(
        "ReferralProgramReferrer",
        on_delete=models.CASCADE,
        related_name="redeemers",
        related_query_name="redeemer",
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    referral_program: models.ForeignKey = models.ForeignKey(
        "ReferralProgram",
        on_delete=models.CASCADE,
        related_name="redeemers",
        related_query_name="redeemer",
    )
    points_awarded: models.PositiveIntegerField = models.PositiveIntegerField(null=True, blank=True)
