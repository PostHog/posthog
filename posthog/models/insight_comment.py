from django.db import models


class InsightComment(models.Model):
    insight: models.ForeignKey = models.ForeignKey(
        "DashboardItem", related_name="comments", on_delete=models.CASCADE, null=False,
    )
    comment: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at: models.DateTimeField = models.DateTimeField(null=True, blank=True, auto_now_add=True)
