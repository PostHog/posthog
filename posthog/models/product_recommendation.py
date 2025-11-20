from typing import TYPE_CHECKING

from django.db import models

from posthog.models.utils import UUIDTModel

if TYPE_CHECKING:
    pass


class ProductRecommendation(UUIDTModel):
    """
    Stores next best product recommendations for organizations.

    Calculated by analyzing product combo patterns across all organizations
    and finding the most common next product for each org's current combo.
    """

    organization = models.OneToOneField(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="product_recommendation",
    )
    recommended_product = models.CharField(
        max_length=255,
        help_text="The product type recommended as the next best product",
    )
    combo_count = models.IntegerField(
        help_text="Number of organizations that have this product combo",
    )
    calculated_at = models.DateTimeField(
        help_text="When this recommendation was calculated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "calculated_at"]),
            models.Index(fields=["recommended_product"]),
        ]

    def __str__(self) -> str:
        return f"{self.organization.name} -> {self.recommended_product}"
