from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.team import Team
from posthog.rbac.decorators import field_access_control


class TeamEventsTableConfig(TeamScopedRootMixin):
    """The events table a project chose for itself during the move from events to events_json.

    posthog.models.event.new_events_schema reads it. Delete this model with the helpers there once every project
    reads events_json. The row belongs to the project's root team, so child environments share one choice.
    """

    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False)

    # None means the project made no choice, so the staff switches and the rollout decide.
    use_new_events_table = field_access_control(models.BooleanField(null=True, blank=True), "project", "admin")
