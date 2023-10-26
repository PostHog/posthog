import dataclasses
import json
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

import structlog
from django.core.paginator import Paginator
from django.db import models
from django.utils import timezone

from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.user import User
from posthog.models.utils import UUIDT, UUIDModel

logger = structlog.get_logger(__name__)

ActivityScope = Literal[
    "FeatureFlag",
    "Person",
    "Insight",
    "Plugin",
    "PluginConfig",
    "SessionRecordingPlaylist",
    "EventDefinition",
    "PropertyDefinition",
    "Notebook",
]
ChangeAction = Literal["changed", "created", "deleted", "merged", "split", "exported"]


@dataclasses.dataclass(frozen=True)
class Change:
    type: ActivityScope
    action: ChangeAction
    field: Optional[str] = None
    before: Optional[Any] = None
    after: Optional[Any] = None


@dataclasses.dataclass(frozen=True)
class Trigger:
    job_type: str
    job_id: str
    payload: Dict


@dataclasses.dataclass(frozen=True)
class Detail:
    changes: Optional[List[Change]] = None
    trigger: Optional[Trigger] = None
    name: Optional[str] = None
    short_id: Optional[str] = None
    type: Optional[str] = None


class ActivityDetailEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (Detail, Change, Trigger)):
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
            )
        ]
        indexes = [models.Index(fields=["team_id", "scope", "item_id"])]

    team_id = models.PositiveIntegerField(null=True)
    organization_id = models.UUIDField(null=True)
    user = models.ForeignKey("posthog.User", null=True, on_delete=models.SET_NULL)
    # If truthy, user can be unset and this indicates a 'system' user made activity asynchronously
    is_system = models.BooleanField(null=True)

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


field_exclusions: Dict[ActivityScope, List[str]] = {
    "Notebook": [
        "id",
        "last_modified_at",
        "last_modified_by",
        "created_at",
        "created_by",
        "text_content",
    ],
    "FeatureFlag": [
        "id",
        "created_at",
        "created_by",
        "is_simple_flag",
        "experiment",
        "team",
        "featureflagoverride",
    ],
    "Person": [
        "id",
        "uuid",
        "distinct_ids",
        "name",
        "created_at",
        "is_identified",
        "persondistinctid",
        "cohort",
        "cohortpeople",
        "properties_last_updated_at",
        "properties_last_operation",
        "team",
        "version",
        "is_user",
    ],
    "Insight": [
        "id",
        "filters_hash",
        "created_at",
        "refreshing",
        "dive_dashboard",
        "updated_at",
        "type",
        "funnel",
        "last_modified_at",
        "layouts",
        "color",
        "order",
        "result",
        "dashboard",
        "last_refresh",
        "saved",
        "is_sample",
        "refresh_attempt",
        "last_modified_by",
        "short_id",
        "created_by",
        "insightviewed",
        "dashboardtile",
        "caching_states",
    ],
    "SessionRecordingPlaylist": [
        "id",
        "short_id",
        "created_at",
        "created_by",
        "last_modified_at",
        "last_modified_by",
    ],
    "EventDefinition": [
        "eventdefinition_ptr_id",
        "id",
        "created_at",
        "_state",
        "deprecated_tags",
        "team_id",
        "updated_at",
        "owner_id",
        "query_usage_30_day",
        "verified_at",
        "verified_by",
        "updated_by",
        "post_to_slack",
    ],
    "PropertyDefinition": [
        "propertydefinition_ptr_id",
        "id",
        "created_at",
        "_state",
        "deprecated_tags",
        "team_id",
        "updated_at",
        "owner_id",
        "query_usage_30_day",
        "volume_30_day",
        "verified_at",
        "verified_by",
        "updated_by",
        "post_to_slack",
        "property_type_format",
    ],
}


def describe_change(m: Any) -> Union[str, Dict]:
    if isinstance(m, Dashboard):
        return {"id": m.id, "name": m.name}
    if isinstance(m, DashboardTile):
        description = {"dashboard": {"id": m.dashboard.id, "name": m.dashboard.name}}
        if m.insight:
            description["insight"] = {"id": m.insight.id}
        if m.text:
            description["text"] = {"id": m.text.id}
        return description
    else:
        return str(m)


def _read_through_relation(relation: models.Manager) -> List[Union[Dict, str]]:
    described_models = [describe_change(r) for r in relation.all()]

    if all(isinstance(elem, str) for elem in described_models):
        # definitely a list of strings now but mypy doesn't know that
        described_models = sorted(described_models)  # type: ignore

    return described_models


def changes_between(
    model_type: Literal["FeatureFlag", "Person", "Insight", "SessionRecordingPlaylist", "Notebook"],
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
        fields = current._meta.get_fields() if current is not None else []

        filtered_fields = [f.name for f in fields if f.name not in field_exclusions[model_type]]
        for field in filtered_fields:
            left = getattr(previous, field, None)
            if isinstance(left, models.Manager):
                left = _read_through_relation(left)

            right = getattr(current, field, None)
            if isinstance(right, models.Manager):
                right = _read_through_relation(right)

            if field == "tagged_items":
                field = "tags"  # or the UI needs to be coupled to this internal backend naming

            if field == "dashboards" and "dashboard_tiles" in filtered_fields:
                # only process dashboard_tiles when it is present. It supersedes dashboards
                continue

            if model_type == "Insight" and field == "dashboard_tiles":
                # the api exposes this as dashboards and that's what the activity describers expect
                field = "dashboards"

            if left is None and right is not None:
                changes.append(Change(type=model_type, field=field, action="created", after=right))
            elif right is None and left is not None:
                changes.append(Change(type=model_type, field=field, action="deleted", before=left))
            elif left != right:
                changes.append(
                    Change(
                        type=model_type,
                        field=field,
                        action="changed",
                        before=left,
                        after=right,
                    )
                )

    return changes


def dict_changes_between(
    model_type: ActivityScope,
    previous: Dict[Any, Any],
    new: Dict[Any, Any],
    use_field_exclusions: bool = False,
) -> List[Change]:
    """
    Identifies changes between two dictionaries by comparing fields
    """
    changes: List[Change] = []

    if previous == new:
        return changes

    previous = previous or {}
    new = new or {}

    fields = set(list(previous.keys()) + list(new.keys()))
    if use_field_exclusions:
        fields = fields - set(field_exclusions.get(model_type, []))

    for field in fields:
        previous_value = previous.get(field, None)
        new_value = new.get(field, None)

        if previous_value is None and new_value is not None:
            changes.append(Change(type=model_type, field=field, action="created", after=new_value))
        elif new_value is None and previous_value is not None:
            changes.append(
                Change(
                    type=model_type,
                    field=field,
                    action="deleted",
                    before=previous_value,
                )
            )
        elif previous_value != new_value:
            changes.append(
                Change(
                    type=model_type,
                    field=field,
                    action="changed",
                    before=previous_value,
                    after=new_value,
                )
            )

    return changes


def log_activity(
    organization_id: Optional[UUIDT],
    team_id: int,
    user: User | None,
    item_id: Optional[Union[int, str, UUIDT]],
    scope: str,
    activity: str,
    detail: Detail,
    force_save: bool = False,
) -> None:
    try:
        if activity == "updated" and (detail.changes is None or len(detail.changes) == 0) and not force_save:
            logger.warn(
                "activity_log.ignore_update_activity_no_changes",
                team_id=team_id,
                organization_id=organization_id,
                user_id=user.id if user else None,
                scope=scope,
            )
            return

        ActivityLog.objects.create(
            organization_id=organization_id,
            team_id=team_id,
            user=user,
            is_system=user is None,
            item_id=str(item_id),
            scope=scope,
            activity=activity,
            detail=detail,
        )
    except Exception as e:
        logger.warn(
            "activity_log.failed_to_write_to_activity_log",
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


def get_activity_page(activity_query: models.QuerySet, limit: int = 10, page: int = 1) -> ActivityPage:
    paginator = Paginator(activity_query, limit)
    activity_page = paginator.page(page)

    return ActivityPage(
        results=list(activity_page.object_list),
        total_count=paginator.count,
        limit=limit,
        has_next=activity_page.has_next(),
        has_previous=activity_page.has_previous(),
    )


def load_activity(
    scope: ActivityScope,
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

    return get_activity_page(activity_query, limit, page)


def load_all_activity(scope_list: List[ActivityScope], team_id: int, limit: int = 10, page: int = 1):
    activity_query = (
        ActivityLog.objects.select_related("user").filter(team_id=team_id, scope__in=scope_list).order_by("-created_at")
    )

    return get_activity_page(activity_query, limit, page)
