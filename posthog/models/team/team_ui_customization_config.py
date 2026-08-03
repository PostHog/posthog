import logging

from django.db import models

from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal
from posthog.rbac.decorators import field_access_control

logger = logging.getLogger(__name__)


# Intentionally not inheriting from UUIDModel/UUIDTModel because we're using a OneToOneField
# and therefore using the exact same primary key as the Team model.
class TeamUICustomizationConfig(models.Model):
    # db_constraint=False: a DB-level FK constraint pointing at posthog_team takes a
    # SHARE ROW EXCLUSIVE lock on the hot parent table while it's created (see the
    # HotTableAlterPolicy migration analyzer); Django's app-level CASCADE is enough here.
    team = models.OneToOneField(
        Team,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="ui_customization_config",
        db_constraint=False,
    )

    default_ui_configuration = field_access_control(
        models.JSONField(
            null=True,
            blank=True,
            help_text="Project-wide default sidebar/UI configuration, shaped like the UserUIConfiguration "
            "schema. Members who haven't customized their own UI inherit it. NULL means the project has no "
            "default and members see everything.",
        ),
        "project",
        "admin",
    )


register_team_extension_signal(TeamUICustomizationConfig, logger=logger)
