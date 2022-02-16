import copy
from datetime import datetime
from typing import Dict

from django.db import models
from django.utils import timezone


def as_deletion_state(metadata: Dict) -> Dict:
    """
    Deletion state is being saved without access to a DRF serializer
    So replace datetime field with a string or it can't be serialized to JSON
    """
    state = copy.deepcopy(metadata)
    if state["created_at"] and isinstance(state["created_at"], datetime):
        state["created_at"] = state["created_at"].isoformat()
    return state


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

    @staticmethod
    def save_version(serializer, action: str) -> None:
        HistoricalVersion(
            state=serializer.data,
            name=serializer.instance.__class__.__name__,
            item_id=serializer.instance.id,
            action=action,
            created_by_name=serializer.context["request"].user.first_name,
            created_by_email=serializer.context["request"].user.email,
            created_by_id=serializer.context["request"].user.id,
            team_id=serializer.context["team_id"],
        ).save()

    @staticmethod
    def save_deletion(instance, item_id: int, team_id: int, metadata: Dict, user: Dict) -> None:
        """
        When deleting in AnalyticsDestroyModelMixin we can't inject a serializer instance.
        And django rest framework doesn't provide the serializer in its destroy hook.

        Instead, we capture a dictionary of metadata (which is a subset of the instance state)

        This means we don't capture all object state on deletion.
        In most cases this will be fine and the previous HistoricalVersion will contain any state needed
        """
        state = as_deletion_state(metadata)

        version = HistoricalVersion(
            state=state,
            name=instance.__class__.__name__,
            action="delete",
            item_id=item_id,
            created_by_name=user["first_name"],
            created_by_email=user["email"],
            created_by_id=user["id"],
            team_id=team_id,
        )
        version.save()


class HistoryLoggingMixin:
    def perform_create(self, serializer):
        serializer.save()
        HistoricalVersion.save_version(serializer, "create")

    def perform_update(self, serializer):
        serializer.save()
        HistoricalVersion.save_version(serializer, "update")
