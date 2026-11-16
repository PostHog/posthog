from django.db import models

from posthog.models.scoping.manager import EnvironmentScopedManager
from posthog.models.team import Team
from posthog.rbac.decorators import field_access_control


class TeamEventsTableConfig(models.Model):
    """Whether a project opted in to events_json before PostHog moves it there.

    posthog.models.event.new_events_schema reads it. Delete this model with the helpers there once every project
    reads events_json. The row is keyed on the team whose queries it switches, which is the id the rollout flag
    and the staff list match. A child environment therefore opts in for itself.
    """

    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False)

    use_new_events_table = field_access_control(
        models.BooleanField(default=False, db_default=False), "project", "admin"
    )

    objects = EnvironmentScopedManager()
