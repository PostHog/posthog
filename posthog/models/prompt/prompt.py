from django.db import models
from django.utils import timezone


class UserPromptSequenceState(models.Model):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "key"], name="unique sequence key for user")]

    user: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE)
    key: models.CharField = models.CharField(max_length=400)

    last_updated_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    step: models.IntegerField = models.IntegerField(default=0)
    completed: models.BooleanField = models.BooleanField(default=False)
    dismissed: models.BooleanField = models.BooleanField(default=False)
