from typing import Any, cast

from django.db import models
from django.db.models.deletion import Collector

LOCK_FIELD = "is_managed_by_terraform"


def release_terraform_lock(collector: Collector, field: models.ForeignKey, sub_objs: Any, using: str) -> None:
    """on_delete for terraform_managed_by. When the Terraform account leaves the organization, disable
    the lock and set the account to null in the same delete. An enabled lock with no account refuses
    every write, so without this step nobody could change the access rules of the project.

    The lock update is queued first. The collector runs its field updates in insertion order against
    one queryset, which filters on the key that the second update sets to null.
    """
    lock_field = cast(models.Field, field.model._meta.get_field(LOCK_FIELD))
    collector.add_field_update(lock_field, False, sub_objs)
    collector.add_field_update(field, None, sub_objs)


release_terraform_lock.lazy_sub_objs = True  # type: ignore[attr-defined]


class TeamAccessControlConfig(models.Model):
    """Per-project access control settings. A row exists only after the first write. Read it
    through get_or_create_team_extension."""

    # db_constraint=False so that the CREATE TABLE takes no lock on posthog_team.
    # related_name="+" keeps both relations off the product boundary, which the model crossing
    # guard enforces.
    team = models.OneToOneField(
        "posthog.Team", on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+"
    )
    # When true, only terraform_managed_by may change this project's access rules. Admins turn it off and on.
    # A rule write from Terraform turns it on.
    is_managed_by_terraform = models.BooleanField(default=False, db_default=False)
    # The account behind the API key Terraform uses for this project, kept while the lock is off so
    # that an admin can turn it on again. When the account leaves the organization, the field
    # becomes null and the lock is disabled, so the rules return to the UI.
    terraform_managed_by = models.ForeignKey(
        "posthog.OrganizationMembership",
        null=True,
        blank=True,
        on_delete=release_terraform_lock,
        related_name="+",
    )
    # Set on every Terraform write of an access rule in this project.
    terraform_last_applied_at = models.DateTimeField(null=True, blank=True)
