import logging

from django.db import models

from posthog.models.team import Team
from posthog.models.team.extensions import register_team_extension_signal

logger = logging.getLogger(__name__)


class TeamAccessControlConfig(models.Model):
    # db_constraint=False keeps the CREATE TABLE from taking a lock on posthog_team
    team = models.OneToOneField(Team, on_delete=models.CASCADE, primary_key=True, db_constraint=False)

    lock_terraform_managed_rules = models.BooleanField(
        default=False,
        db_default=False,
        help_text=(
            "When on, access control rules that Terraform manages can only be changed by Terraform. "
            "Every other caller is refused."
        ),
    )


register_team_extension_signal(TeamAccessControlConfig, logger=logger)


def terraform_lock_enabled(team_id: int) -> bool:
    """Read the lock without creating the extension row - this runs on every access control write."""
    return TeamAccessControlConfig.objects.filter(team_id=team_id, lock_terraform_managed_rules=True).exists()
