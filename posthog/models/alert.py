from django.db import models
from posthog.models.insight import Insight


def are_alerts_supported_for_insight(insight: Insight) -> bool:
    query = insight.query
    if query is None or query.get("kind") != "TrendsQuery":
        return False
    if query.get("trendsFilter", {}).get("display") != "BoldNumber":
        return False
    return True


class Alert(models.Model):
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE)

    name = models.CharField(max_length=100)
    target_value = models.TextField()
    anomaly_condition = models.JSONField(default=dict)
