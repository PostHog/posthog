from collections.abc import Iterable

from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import RootTeamMixin, UUIDTModel


def tagify(tag: str):
    return tag.strip().lower()


def tagify_filter(tags: Iterable[object]) -> list[str]:
    """The stored tag names a list filter's raw input matches, so `Finance` finds the tag saved as `finance`."""
    return sorted({name for tag in tags if isinstance(tag, str) and (name := tagify(tag))})


class Tag(ModelActivityMixin, UUIDTModel, RootTeamMixin):
    name = models.CharField(max_length=255)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    class Meta:
        unique_together = ("name", "team")

    def __str__(self):
        return self.name
