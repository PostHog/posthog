from django.db import models
from posthog.models.utils import UUIDModel
from posthog.models.utils import sane_repr
from posthog.models.team import Team


class StreamConfig(UUIDModel):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    stream_url = models.TextField()
    events = models.JSONField(default=list)

    def __str__(self):
        return f"{self.team.name} - {self.stream_url}"

    __repr__ = sane_repr("id", "team_id", "stream_url")
