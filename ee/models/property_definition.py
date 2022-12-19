from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.property_definition import PropertyDefinition


class EnterprisePropertyDefinition(PropertyDefinition):
    description: models.TextField = models.TextField(blank=True, null=True, default="")
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey("posthog.User", null=True, on_delete=models.SET_NULL, blank=True)

    # Deprecated in favour of app-wide tagging model. See EnterpriseTaggedItem
    deprecated_tags: ArrayField = ArrayField(models.CharField(max_length=32), null=True, blank=True, default=list)
    deprecated_tags_v2: ArrayField = ArrayField(
        models.CharField(max_length=32), null=True, blank=True, default=None, db_column="tags"
    )
