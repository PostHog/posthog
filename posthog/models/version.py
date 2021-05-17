from django.db import models


class Version(models.Model):
    instance_key: models.ForeignKey = models.ForeignKey(
        "DashboardItem", related_name="versions", on_delete=models.CASCADE, null=True, blank=True,
    )
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE)
    previous_state: models.JSONField = models.JSONField(default=dict)
    update: models.JSONField = models.JSONField(default=dict)
    comment: models.CharField = models.CharField(max_length=400, null=True, blank=True)
