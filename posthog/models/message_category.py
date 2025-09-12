from django.db import models

from posthog.models.utils import UUIDTModel


class MessageCategoryType(models.TextChoices):
    MARKETING = "marketing"
    TRANSACTIONAL = "transactional"


class MessageCategory(UUIDTModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(default=False)
    key = models.CharField(max_length=64)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    public_description = models.TextField(blank=True, default="")
    category_type = models.CharField(
        max_length=32, choices=MessageCategoryType.choices, default=MessageCategoryType.MARKETING.value
    )

    class Meta:
        unique_together = (
            "team",
            "key",
        )
        verbose_name_plural = "message categories"

    def __str__(self) -> str:
        return self.name
