from django.contrib.postgres.fields import ArrayField
from django.db import models

from products.event_definitions.backend.models import PropertyDefinition
from products.event_definitions.backend.models.enterprise_copies import (
    PROPERTY_DEFINITION_COPIES,
    copy_enterprise_fields,
    saves_updated_at,
)


class EnterprisePropertyDefinition(PropertyDefinition):
    description = models.TextField(blank=True, null=True, default="")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey("posthog.User", null=True, on_delete=models.SET_NULL, blank=True)

    verified = models.BooleanField(default=False, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    verified_by = models.ForeignKey(
        "posthog.User",
        null=True,
        on_delete=models.SET_NULL,
        blank=True,
        related_name="property_verifying_user",
    )
    hidden = models.BooleanField(blank=True, null=True, default=False)

    # Deprecated in favour of app-wide tagging model. See EnterpriseTaggedItem
    deprecated_tags: ArrayField = ArrayField(models.CharField(max_length=32), null=True, blank=True, default=list)
    deprecated_tags_v2: ArrayField = ArrayField(
        models.CharField(max_length=32),
        null=True,
        blank=True,
        default=None,
        db_column="tags",
    )

    def save(self, *args, **kwargs) -> None:
        update_fields = kwargs.get("update_fields")
        kwargs["update_fields"] = copy_enterprise_fields(self, PROPERTY_DEFINITION_COPIES, update_fields)
        super().save(*args, **kwargs)
        if saves_updated_at(update_fields):
            PropertyDefinition.objects.filter(pk=self.pk).update(base_updated_at=self.updated_at)
