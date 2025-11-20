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
    product_sequence_state_before = models.JSONField(
        default=list,
        help_text="Ordered list of products the organization had before this recommendation",
    )
    num_products_before = models.IntegerField(
        default=0,
        help_text="Number of products the organization had before this recommendation",
    )
    calculated_at = models.DateTimeField(
        help_text="When this recommendation was calculated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.organization.name} -> {self.recommended_product}"
