import datetime
import json
from typing import Dict

from django.db import models
from django.utils import timezone

from posthog.models import FeatureFlag
from posthog.models.utils import UUIDModel


class HistoricalVersionJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, models.base.ModelState):
            return None
        if isinstance(obj, FeatureFlag):
            return obj.__dict__
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()

        return json.JSONEncoder.default(self, obj)


class HistoricalVersion(UUIDModel):
    """
    We don't store foreign key references cos the referenced model will change or be deleted.
    The history log should hold the state at the time it is written not the time it is read

    Everything in the log must have either a team id or an organization id
    """

    class Action(models.TextChoices):
        Create = "create"
        Update = "update"
        Delete = "delete"

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
        indexes = [
            models.Index(fields=["item_id", "team_id", "name"]),
        ]

    # JSON of the historical item
    state = models.JSONField(null=False, encoder=HistoricalVersionJSONEncoder)
    # e.g. FeatureFlags - in practice this will be the name of a model class
    name = models.fields.CharField(max_length=79, null=False)

    action = models.CharField(max_length=6, choices=Action.choices, blank=True, null=False)

    # the id of the item being versioned
    # this might be a numerical id, short id, or UUID, so each will be converted to string
    # it will be used to lookup rows with exactly matching item_ids
    # it probably only needs to be 36 characters in order to hold a GUID
    # but 72 may be useful to avoid a migration in future
    item_id = models.fields.CharField(max_length=72, null=False)

    # to avoid an integer version field for ordering revisions
    versioned_at: models.DateTimeField = models.DateTimeField(default=timezone.now)

    # created_by_X does not use a foreign key
    # so that deletion of users does not erase history

    # user that caused the change
    created_by_email = models.EmailField(null=False)
    # max length from User model
    created_by_name = models.CharField(max_length=150, null=False)
    created_by_id = models.PositiveIntegerField(null=False)

    # team or organization that contains the change
    team_id = models.PositiveIntegerField(null=True)
    organization_id = models.UUIDField(null=True)

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
    def save_deletion(instance, item_id: int, team_id: int, user: Dict) -> None:
        version = HistoricalVersion(
            state=instance,
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
