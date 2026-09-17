from typing import Optional

from django.db import models

from posthog.models.team import Team


class TeamEventVolume(models.Model):
    # Rows come from posthog.tasks.team_event_volume, not from team creation, so this is not
    # registered as a team extension signal.
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False)
    events_last_year = models.BigIntegerField()
    computed_at = models.DateTimeField()


def events_last_year_for(team_id: int) -> Optional[int]:
    return TeamEventVolume.objects.filter(team_id=team_id).values_list("events_last_year", flat=True).first()
