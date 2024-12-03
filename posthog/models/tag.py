from django.db import models

from posthog.models.utils import UUIDModel


def tagify(tag: str):
    return tag.strip().lower()


class Tag(UUIDModel):
    name = models.CharField(max_length=255)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    class Meta:
        unique_together = ("name", "team")

    def __str__(self):
        return self.name
