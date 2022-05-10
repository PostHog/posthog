import dataclasses
import json
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

import structlog
from django.core.paginator import Paginator
from django.db import models
from django.utils import timezone

from posthog.models.user import User
from posthog.models.utils import UUIDT, UUIDModel

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class Change:
    type: Literal["FeatureFlag", "Person", "Insight"]
    action: Literal["changed", "created", "deleted", "merged", "split"]
    field: Optional[str] = None
    before: Optional[Any] = None
    after: Optional[Any] = None


@dataclasses.dataclass(frozen=True)
class Merge:
    type: Literal["Person"]
    source: Optional[Any] = None
    target: Optional[Any] = None


@dataclasses.dataclass(frozen=True)
class Detail:
    changes: Optional[List[Change]] = None
    merge: Optional[Merge] = None
    name: Optional[str] = None
    short_id: Optional[str] = None


class ActivityDetailEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (Detail, Change, Merge)):
            return obj.__dict__
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, UUIDT):
            return str(obj)
        if isinstance(obj, User):
            return {"first_name": obj.first_name, "email": obj.email}

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


field_exclusions: Dict[Literal["FeatureFlag", "Person", "Insight"], List[str]] = {
    "FeatureFlag": ["id", "created_at", "created_by", "is_simple_flag",],
    "Person": ["id", "uuid", "distinct_ids", "name", "created_at", "is_identified",],
    "Insight": [
        "id",
        "filters_hash",
        "created_at",
        "refreshing",
        "dive_dashboard",
        "updated_at",
        "type",
        "funnel",
        "deprecated_tags",
        "last_modified_at",
        "layouts",
        "color",
        "order",
        "result",
        "dashboard",
        "last_refresh",
        "saved",
        "is_sample",
    ],
}


def changes_between(
    model_type: Literal["FeatureFlag", "Person", "Insight"],
    previous: Optional[models.Model],
    current: Optional[models.Model],
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

        # TODO how to include tags in the fields assessed
        filtered_fields = [f.name for f in fields if f.name not in field_exclusions[model_type]]
        for field in filtered_fields:
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


@dataclasses.dataclass(frozen=True)
class ActivityPage:
    total_count: int
    limit: int
    has_next: bool
    has_previous: bool
    results: List[ActivityLog]


def load_activity(
    scope: Literal["FeatureFlag", "Person", "Insight"],
    team_id: int,
    item_id: Optional[int] = None,
    limit: int = 10,
    page: int = 1,
) -> ActivityPage:
    # TODO in follow-up to posthog #8931 selecting specific fields into a return type from this query

    activity_query = (
        ActivityLog.objects.select_related("user").filter(team_id=team_id, scope=scope).order_by("-created_at")
    )

    if item_id is not None:
        activity_query = activity_query.filter(item_id=item_id)

    paginator = Paginator(activity_query, limit)
    activity_page = paginator.page(page)

    return ActivityPage(
        results=list(activity_page.object_list),
        total_count=paginator.count,
        limit=limit,
        has_next=activity_page.has_next(),
        has_previous=activity_page.has_previous(),
    )
