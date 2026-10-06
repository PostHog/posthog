import logging

from django.db import models

from posthog.models.team.extensions import register_team_extension_signal
from posthog.rbac.decorators import field_access_control

logger = logging.getLogger(__name__)

MAX_DEFAULT_FILTERS = 20


class TeamDefaultFiltersConfig(models.Model):
    # db_constraint=False: a real FK constraint would take a SHARE ROW EXCLUSIVE
    # lock on posthog_team (a hot table) while migrating.
    # related_name="+": readers come in through `Team.default_filters_config` instead.
    team = models.OneToOneField(
        "posthog.Team", on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+"
    )

    # Property filters added to the query of every insight that has `applyDefaultFilters` turned on,
    # resolved when the query runs. Same entry shapes as `Team.test_account_filters`, validated by the
    # team serializer.
    filters = field_access_control(models.JSONField(default=list), "project", "admin")

    # Whether new insights start with `applyDefaultFilters` turned on. Existing insights are not affected.
    apply_to_new_insights = field_access_control(models.BooleanField(default=False), "project", "admin")


register_team_extension_signal(TeamDefaultFiltersConfig, logger=logger)
