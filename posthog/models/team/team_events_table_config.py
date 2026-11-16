from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.team import Team
from posthog.rbac.decorators import field_access_control


class TeamEventsTableConfig(TeamScopedRootMixin):
    """Whether a project opted in to events_json before PostHog moves it there.

    posthog.models.event.new_events_schema reads it. Delete this model with the helpers there once every project
    reads events_json. The row belongs to the project's root team, so child environments share one opt-in.
    """

    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False)

    use_new_events_table = field_access_control(models.BooleanField(null=True, blank=True), "project", "admin")
