import logging

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)

DEFAULT_STALE_EVENT_DAYS = 30


class TeamDataManagementConfig(models.Model):
    """How long an event can go without arriving before PostHog calls it stale."""

    # db_constraint=False: a real FK constraint would take a SHARE ROW EXCLUSIVE
    # lock on posthog_team (a hot table) while migrating.
    # related_name="+": readers come in through `Team.data_management_config` instead.
    team = models.OneToOneField(
        "posthog.Team", on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+"
    )

    stale_event_days = models.PositiveSmallIntegerField(
        default=DEFAULT_STALE_EVENT_DAYS,
        db_default=DEFAULT_STALE_EVENT_DAYS,
        validators=[MinValueValidator(1), MaxValueValidator(365)],
    )


register_team_extension_signal(TeamDataManagementConfig, logger=logger)
