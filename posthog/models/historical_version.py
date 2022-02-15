from django.db import models
from django.utils import timezone


class HistoricalVersion(models.Model):
    """
    We don't _only_ store foreign references cos the referenced model might get deleted.
    The history log should be relatively immutable

    Everything in the log must have either a team id or an organization id
    """

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization_id", "team_id", "name", "versioned_at"], name="unique_version"
            ),
            models.CheckConstraint(
                check=models.Q(team_id__isnull=False) | models.Q(organization_id__isnull=False),
                name="must_have_team_or_organization_id",
            ),
        ]

    # JSON of the historical item
    state = models.JSONField(null=False)
    # e.g. feature_flags
    name = models.fields.TextField(null=False)
    # TODO will this only be create, update, or delete
    action = models.fields.TextField(null=False)

    # the id of the item being versioned
    item_id = models.fields.PositiveIntegerField(null=False)

    # to avoid an integer version field for ordering revisions
    versioned_at: models.DateTimeField = models.DateTimeField(default=timezone.now)

    # user that caused the change
    created_by_email = models.EmailField(null=False)
    created_by_name = models.TextField(null=False)
    created_by_id = models.PositiveIntegerField(null=False)

    # team or organization that contains the change
    team_id = models.PositiveIntegerField(null=True)
    organization_id = models.UUIDField(primary_key=False, null=True)
