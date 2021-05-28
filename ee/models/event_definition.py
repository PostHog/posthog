from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.event_definition import EventDefinition


class EnterpriseEventDefinition(EventDefinition):
    owner = models.ForeignKey("posthog.User", null=True, on_delete=models.PROTECT, related_name="event_definitions",)
    description: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    tags: ArrayField = ArrayField(models.CharField(max_length=32), null=True, default=list)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey("posthog.User", null=True, on_delete=models.PROTECT, blank=True)

