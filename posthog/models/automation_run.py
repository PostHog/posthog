from django.db import models


class AutomationRun(models.Model):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    status: models.CharField = models.CharField(max_length=24, null=True, blank=True)
    automation: models.ForeignKey = models.ForeignKey("Automation", on_delete=models.CASCADE)
