from django.contrib.postgres.fields import ArrayField
from django.db import models
from django_deprecate_fields import deprecate_field

from posthog.models.event_definition import EventDefinition


class EnterpriseEventDefinition(EventDefinition):
    owner = models.ForeignKey("posthog.User", null=True, on_delete=models.SET_NULL, related_name="event_definitions")
    description: models.TextField = models.TextField(blank=True, null=True, default="")
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey("posthog.User", null=True, on_delete=models.SET_NULL, blank=True)
    verified: models.BooleanField = models.BooleanField(default=False, blank=True)
    verified_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        "posthog.User", null=True, on_delete=models.SET_NULL, blank=True, related_name="verifying_user",
    )

    # Deprecated in favour of app-wide tagging model. See EnterpriseTaggedItem
    deprecated_tags: ArrayField = deprecate_field(
        ArrayField(models.CharField(max_length=32), null=True, blank=True, default=list), return_instead=[],
    )
    tags: ArrayField = deprecate_field(
        ArrayField(models.CharField(max_length=32), null=True, blank=True, default=None), return_instead=[],
    )
