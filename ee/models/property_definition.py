from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.property_definition import PropertyDefinition


class EnterprisePropertyDefinition(PropertyDefinition):
    description: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    tags: ArrayField = ArrayField(models.CharField(max_length=32), null=True, default=list)
