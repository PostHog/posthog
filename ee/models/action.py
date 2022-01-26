from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.action import Action


# EnterpriseAction is a copy of Action with a few additional parameters only available on enterprise plans
class EnterpriseAction(Action):
    owner = models.ForeignKey("posthog.User", null=True, on_delete=models.SET_NULL, related_name="event_definitions",)
    description: models.TextField = models.TextField(blank=True)
    tags: ArrayField = ArrayField(models.CharField(max_length=32), null=True, blank=True, default=list)
