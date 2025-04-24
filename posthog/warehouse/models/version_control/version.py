from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, UUIDModel
from django.db import models


class Version(CreatedMetaFields, UUIDModel):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    content_hash = models.CharField(max_length=128)
    parent_version = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True)
