from typing import Any, List

from django.contrib.postgres.fields import ArrayField
from django.db import models


class Tour(models.Model):
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    cohort: models.ForeignKey = models.ForeignKey("Cohort", on_delete=models.CASCADE)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    name: models.CharField = models.TextField()
    trigger_url_regex: models.CharField = models.TextField()
    delay_ms: models.IntegerField = models.IntegerField(default=0)
    is_active: models.BooleanField = models.BooleanField(default=True)
    steps: ArrayField = ArrayField(models.JSONField(default=dict), null=True, blank=True, default=list)


class TourPerson(models.Model):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["tour", "person"], name="unique person for tour")]

    tour: models.ForeignKey = models.ForeignKey(Tour, on_delete=models.CASCADE)
    person: models.ForeignKey = models.ForeignKey("Person", on_delete=models.CASCADE)
    is_started: models.BooleanField = models.BooleanField(default=False)
