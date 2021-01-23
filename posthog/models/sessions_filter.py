from django.contrib.postgres.fields import JSONField
from django.db import models


class SessionsFilter(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=["team_id", "name"]),
        ]

    name: models.CharField = models.CharField(max_length=400, null=False, blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    filters: JSONField = JSONField(default=dict)
