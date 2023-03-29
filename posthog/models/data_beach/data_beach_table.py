from django.db import models


class DataBeachTableEngine(models.TextChoices):
    APPENDABLE = "appendable", "appendable"  # table you can append to


class DataBeachTable(models.Model):
    team: models.ForeignKey = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name: models.CharField = models.CharField(max_length=255, null=False, blank=False)
    engine: models.CharField = models.CharField(
        max_length=100,
        null=False,
        blank=False,
        choices=DataBeachTableEngine.choices,
        default=DataBeachTableEngine.APPENDABLE,
    )
