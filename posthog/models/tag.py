from django.db import models

from posthog.models.utils import UUIDModel, RootTeamMixin
from posthog.models.activity_logging.model_activity import ModelActivityMixin


def tagify(tag: str):
    return tag.strip().lower()


class Tag(ModelActivityMixin, UUIDModel, RootTeamMixin):
    name = models.CharField(max_length=255)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    class Meta:
        unique_together = ("name", "team")

    def __str__(self):
        return self.name
