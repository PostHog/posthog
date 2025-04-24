import hashlib
from django.db import models
from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UUIDModel


class Content(CreatedMetaFields, UUIDModel):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    content_hash = models.CharField(max_length=128)
    content = models.TextField()

    class Meta:
        unique_together = ("content_hash", "team")

    @staticmethod
    def get_content_hash(content: str) -> str:
        return hashlib.sha1(content.encode("utf-8")).hexdigest()
