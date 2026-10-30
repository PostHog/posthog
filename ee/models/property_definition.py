from django.contrib.postgres.fields import ArrayField
from django.db import models, transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from products.event_definitions.backend.models import PropertyDefinition
from products.event_definitions.backend.models.enterprise_copies import (
    PROPERTY_DEFINITION_COPIED_FIELDS,
    clear_copied_user_ids,
    copy_enterprise_fields,
    lock_base_row,
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
        # One transaction: an overlapping save waits on the row locks, so the copies cannot end up
        # older than this row.
        with transaction.atomic():
            lock_base_row(self, PropertyDefinition)
            super().save(*args, **kwargs)
            copy_enterprise_fields(
                self, PropertyDefinition, PROPERTY_DEFINITION_COPIED_FIELDS, kwargs.get("update_fields")
            )


@receiver(pre_delete, sender="posthog.User")
def _clear_copied_user_ids(sender: type[models.Model], instance: models.Model, **kwargs: object) -> None:
    clear_copied_user_ids(EnterprisePropertyDefinition, PropertyDefinition, ("updated_by", "verified_by"), instance.pk)
