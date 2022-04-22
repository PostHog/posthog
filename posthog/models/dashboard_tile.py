from django.db import models


class DashboardTile(models.Model):
    # Relations
    dashboard = models.ForeignKey("posthog.Dashboard", on_delete=models.CASCADE)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE)

    # Dashboard layout and style
    layouts: models.JSONField = models.JSONField(default=dict)
    color: models.CharField = models.CharField(max_length=400, null=True, blank=True)
