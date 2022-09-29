from django.db import models


class EventBuffer(models.Model):
    event: models.JSONField = models.JSONField(null=True, blank=True)
    process_at: models.DateTimeField = models.DateTimeField()
    locked: models.BooleanField = models.BooleanField()
