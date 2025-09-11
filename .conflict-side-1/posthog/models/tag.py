from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import RootTeamMixin, UUIDTModel


def tagify(tag: str):
    return tag.strip().lower()


class Tag(ModelActivityMixin, UUIDTModel, RootTeamMixin):
    name = models.CharField(max_length=255)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    class Meta:
        unique_together = ("name", "team")

    def __str__(self):
        return self.name
