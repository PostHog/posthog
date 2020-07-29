from django.contrib.postgres.fields import JSONField
from django.db import models


class Insight(models.Model):
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    filters: JSONField = JSONField(default=dict)
    created_at: models.DateTimeField = models.DateTimeField(null=True, blank=True, auto_now_add=True)
    pinned: models.BooleanField = models.BooleanField(default=False)
