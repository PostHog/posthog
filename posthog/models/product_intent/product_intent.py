from django.db import models

from posthog.models.utils import UUIDModel


class ProductIntent(UUIDModel):
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    product_type = models.CharField(max_length=255)
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ["team", "product_type"]

    def __str__(self):
        return f"{self.team.name} - {self.product_type}"
