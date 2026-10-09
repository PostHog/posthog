from django.db import models


class TeamAccessControlConfig(models.Model):
    """Per-project access control settings. A row exists only after the first write. Read it
    through get_or_create_team_extension."""

    # db_constraint=False so that the CREATE TABLE takes no lock on posthog_team.
    # related_name="+" keeps both relations off the product boundary, which the model crossing
    # guard enforces.
    team = models.OneToOneField(
        "posthog.Team", on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+"
    )
    # When true, only managed_by may change this project's access rules. Admins turn it off and on.
    # A rule write from Terraform turns it on.
    managed_by_terraform = models.BooleanField(default=False, db_default=False)
    # The account behind the API key Terraform uses for this project, kept while the lock is off so
    # that an admin can turn it on again. SET_NULL: when the account leaves the organization, the
    # rules return to the UI and are not locked.
    managed_by = models.ForeignKey(
        "posthog.OrganizationMembership", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    managed_at = models.DateTimeField(null=True, blank=True)
