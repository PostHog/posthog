from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class CustomerAnalyticsConfig(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE)

    activity_event = models.JSONField(default=dict)
