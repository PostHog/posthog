from django.db import models

from posthog.models.team import Team


class DataColorTheme(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, null=True, blank=True)

    name = models.CharField(max_length=100)
    colors = models.JSONField(default=list)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "name"], name="unique_name_per_team")]

    def __str__(self):
        return self.name
