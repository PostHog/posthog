from django.db import models

class FollowUpEmail(models.Model):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(
        auto_now_add=True, blank=True
    )