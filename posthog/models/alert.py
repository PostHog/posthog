from django.db import models
from posthog.schema import ChartDisplayType, TrendsQuery
from posthog.models.insight import Insight


def are_alerts_supported_for_insight(insight: Insight) -> bool:
    query = insight.query
    if not isinstance(query, TrendsQuery):
        return False
    if not query.trendsFilter or query.trendsFilter.display != ChartDisplayType.BOLD_NUMBER:
        return False
    return True


class Alert(models.Model):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE)

    name: models.CharField = models.CharField(max_length=100)
    target_value: models.TextField = models.TextField()
    anomaly_condition: models.JSONField = models.JSONField(default=dict)
