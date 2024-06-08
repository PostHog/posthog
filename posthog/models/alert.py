from django.db import models
from typing import Optional
from dataclasses import dataclass


@dataclass
class AbsoluteThreshold:
    lower: Optional[float] = None
    upper: Optional[float] = None


class AnomalyCondition:
    absolute_threshold: AbsoluteThreshold

    def __init__(self, absoluteThreshold: dict):
        self.absolute_threshold = AbsoluteThreshold(**absoluteThreshold)


class Alert(models.Model):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    insight: models.ForeignKey = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE)

    name: models.CharField = models.CharField(max_length=100)
    target_value: models.TextField = models.TextField()
    anomaly_condition: models.JSONField = models.JSONField(default=dict)
