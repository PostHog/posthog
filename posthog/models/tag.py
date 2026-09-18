from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import RootTeamMixin, UUIDTModel


def tagify(tag: str):
    return tag.strip().lower()


class Tag(ModelActivityMixin, UUIDTModel, RootTeamMixin):
    name = models.CharField(max_length=255)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    # A pinned tag was created on purpose through the tags API, so it stays available while nothing
    # carries it. An unpinned tag exists only through the objects that carry it and is removed once
    # the last one drops it (see `cleanup_orphan_tags`).
    pinned = models.BooleanField(default=False, db_default=False)

    class Meta:
        unique_together = ("name", "team")

    def __str__(self):
        return self.name
