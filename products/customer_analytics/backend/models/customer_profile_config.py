from django.db import models

from posthog.models import Team
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class CustomerProfileConfig(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    class Scope(models.TextChoices):
        PERSON = "person", "Person"
        GROUP_0 = "group_0", "Group 0"
        GROUP_1 = "group_1", "Group 1"
        GROUP_2 = "group_2", "Group 2"
        GROUP_3 = "group_3", "Group 3"
        GROUP_4 = "group_4", "Group 4"

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    content = models.JSONField(default=dict)
    sidebar = models.JSONField(default=dict)
    scope = models.CharField(max_length=255, choices=Scope.choices)
