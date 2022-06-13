from django.contrib.postgres.fields import ArrayField
from django.db import models
from django_deprecate_fields import deprecate_field

from posthog.models.property_definition import PropertyDefinition


class EnterprisePropertyDefinition(PropertyDefinition):
    description: models.TextField = models.TextField(blank=True, null=True, default="")
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey("posthog.User", null=True, on_delete=models.SET_NULL, blank=True)

    # Deprecated in favour of app-wide tagging model. See EnterpriseTaggedItem
    deprecated_tags: ArrayField = deprecate_field(
        ArrayField(models.CharField(max_length=32), null=True, blank=True, default=list), return_instead=[],
    )
    tags: ArrayField = deprecate_field(
        ArrayField(models.CharField(max_length=32), null=True, blank=True, default=None), return_instead=[],
    )
