from django.db import models

from posthog.models.team import Team
from posthog.models.utils import RootTeamMixin


class DataColorTheme(RootTeamMixin, models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, null=True, blank=True)
    project = models.ForeignKey("Project", on_delete=models.CASCADE, null=True, blank=True)

    name = models.CharField(max_length=100)
    colors = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(blank=True, null=True)

    def __str__(self):
        return self.name

    @property
    def is_global(self):
        return self.team_id is None
