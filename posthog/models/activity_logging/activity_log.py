import dataclasses
import json
from typing import Any, List, Literal, Optional, Union

import structlog
from django.db import models
from django.utils import timezone

from posthog.models.user import User
from posthog.models.utils import UUIDT, UUIDModel

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class Change:
    type: Literal["FeatureFlag"]
    action: Literal["changed", "created", "deleted"]
    field: Optional[str] = None
    before: Optional[Any] = None
    after: Optional[Any] = None


@dataclasses.dataclass(frozen=True)
class Detail:
    changes: Optional[List[Change]] = None
    name: Optional[str] = None


class ActivityDetailEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Detail):
            return obj.__dict__
        if isinstance(obj, Change):
            return obj.__dict__

        return json.JSONEncoder.default(self, obj)


class ActivityLog(UUIDModel):
    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(team_id__isnull=False) | models.Q(organization_id__isnull=False),
                name="must_have_team_or_organization_id",
            ),
        ]
        indexes = [
            models.Index(fields=["team_id", "scope", "item_id"]),
        ]

    team_id = models.PositiveIntegerField(null=True)
    organization_id = models.UUIDField(null=True)
    user = models.ForeignKey("posthog.User", null=True, on_delete=models.SET_NULL)
    activity = models.fields.CharField(max_length=79, null=False)
    # if scoped to a model this activity log holds the id of the model being logged
    # if not scoped to a model this log might not hold an item_id
    # this might be a numerical id, short id, or UUID, so each will be converted to string
    # it will be used to lookup rows with exactly matching item_ids
    # it probably only needs to be 36 characters in order to hold a GUID
    # but 72 may be useful to avoid a migration in future
    item_id = models.fields.CharField(max_length=72, null=True)
    # e.g. FeatureFlags - this will often be the name of a model class
    scope = models.fields.CharField(max_length=79, null=False)
    detail = models.JSONField(encoder=ActivityDetailEncoder, null=True)
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now)


def changes_between(
    model_type: Literal["FeatureFlag"], previous: Optional[models.Model], current: Optional[models.Model]
) -> List[Change]:
    """
    Identifies changes between two models by comparing fields
    """
    changes: List[Change] = []

    if previous is None and current is None:
        # there are no changes between two things that don't exist
        return changes

    if previous is not None:
        fields = current._meta.fields if current is not None else []

        for field in [f.name for f in fields]:
            left = getattr(previous, field, None)
            right = getattr(current, field, None)

            if left is None and right is not None:
                changes.append(Change(type=model_type, field=field, action="created", after=right,))
            elif right is None and left is not None:
                changes.append(Change(type=model_type, field=field, action="deleted", before=left,))
            elif left != right:
                changes.append(Change(type=model_type, field=field, action="changed", before=left, after=right,))

    return changes


def log_activity(
    organization_id: UUIDT,
    team_id: int,
    user: User,
    item_id: Optional[Union[int, str, UUIDT]],
    scope: str,
    activity: str,
    detail: Detail,
) -> None:
    try:
        if activity == "updated" and (detail.changes is None or len(detail.changes) == 0):
            logger.warn(
                "ignore_update_activity_no_changes",
                team_id=team_id,
                organization_id=organization_id,
                user_id=user.id,
                scope=scope,
            )
            return

        ActivityLog.objects.create(
            organization_id=organization_id,
            team_id=team_id,
            user=user,
            item_id=str(item_id),
            scope=scope,
            activity=activity,
            detail=detail,
        )
    except Exception as e:
        logger.warn(
            "failed to write activity log",
            team=team_id,
            organization_id=organization_id,
            scope=scope,
            activity=activity,
            exception=e,
        )


def load_activity(scope: Literal["FeatureFlag"], team_id: int, item_id: Optional[int] = None):
    # TODO in follow-up to posthog#8931 paging and selecting specific fields into a return type from this query
    activity_query = (
        ActivityLog.objects.select_related("user").filter(team_id=team_id, scope=scope).order_by("-created_at")
    )

    if item_id is not None:
        activity_query.filter(item_id=item_id)
    activities = list(activity_query[:10])

    return activities
