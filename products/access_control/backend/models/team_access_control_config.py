from django.db import models


class TeamAccessControlConfig(models.Model):
    """Per-project access control settings. A row exists only once something writes one, read
    through get_or_create_team_extension."""

    # db_constraint=False keeps the CREATE TABLE from taking a lock on posthog_team
    team = models.OneToOneField("posthog.Team", on_delete=models.CASCADE, primary_key=True, db_constraint=False)
    # The account whose requests may change this project's access rules, for a project managed
    # with Terraform. Null means the UI manages them. SET_NULL so that removing the account from
    # the organization hands the rules back to the UI instead of leaving them locked.
    managed_by = models.ForeignKey(
        "posthog.OrganizationMembership",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="managed_access_control_configs",
    )
    managed_at = models.DateTimeField(null=True, blank=True)
