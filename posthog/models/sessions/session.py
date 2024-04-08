from django.db import models

class Session(models.Model):
    # we don't currently use this anywhere
    class Meta:
        unique_together = ("team", "session_id")

    session_id: models.CharField = models.CharField(unique=True, max_length=200)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
