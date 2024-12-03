from django.db import models


class EventBuffer(models.Model):
    event = models.JSONField(null=True, blank=True)
    process_at = models.DateTimeField()
    locked = models.BooleanField()
