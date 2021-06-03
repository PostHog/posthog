from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.property_definition import PropertyDefinition


class EnterprisePropertyDefinition(PropertyDefinition):
    description: models.CharField = models.CharField(max_length=400, blank=True)
    tags: ArrayField = ArrayField(models.CharField(max_length=32), null=True, blank=True, default=list)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey("posthog.User", null=True, on_delete=models.SET_NULL, blank=True)
