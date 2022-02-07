from django.db import models

from posthog.models.utils import UUIDModel


class Tag(UUIDModel):
    name: models.SlugField = models.SlugField()
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)

    class Meta:
        unique_together = ("name", "team")

    def __str__(self):
        return self.name
