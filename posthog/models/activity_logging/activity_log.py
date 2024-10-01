import dataclasses
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional, Union
from uuid import UUID

import structlog
from django.core.paginator import Paginator
from django.core.exceptions import ObjectDoesNotExist

from django.db import models
from django.utils import timezone
from django.conf import settings

from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.user import User
from posthog.models.utils import UUIDT, UUIDModel


logger = structlog.get_logger(__name__)

ActivityScope = Literal[
    "Cohort",
    "FeatureFlag",
    "Person",
    "Insight",
    "Plugin",
    "PluginConfig",
    "DataManagement",
    "EventDefinition",
    "PropertyDefinition",
    "Notebook",
    "Dashboard",
    "Replay",
    "Experiment",
    "Survey",
    "EarlyAccessFeature",
    "SessionRecordingPlaylist",
    "Comment",
    "Team",
    "Project",
    "ErrorTrackingGroup",
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
    payload: dict


@dataclasses.dataclass(frozen=True)
class Detail:
    # The display name of the item in question
    name: Optional[str] = None
    # The short_id if it has one
    short_id: Optional[str] = None
    type: Optional[str] = None
    changes: Optional[list[Change]] = None
    trigger: Optional[Trigger] = None


class ActivityDetailEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Detail | Change | Trigger):
            return obj.__dict__
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, UUIDT):
            return str(obj)
        if isinstance(obj, User):
            return {"first_name": obj.first_name, "email": obj.email}
        if isinstance(obj, float):
            # more precision than we'll need but avoids rounding too unnecessarily
            return format(obj, ".6f").rstrip("0").rstrip(".")
        if isinstance(obj, Decimal):
            # more precision than we'll need but avoids rounding too unnecessarily
            return format(obj, ".6f").rstrip("0").rstrip(".")
        if isinstance(obj, FeatureFlag):
            return {
                "id": obj.id,
                "key": obj.key,
                "name": obj.name,
                "filters": obj.filters,
                "team_id": obj.team_id,
                "deleted": obj.deleted,
                "active": obj.active,
            }

        return json.JSONEncoder.default(self, obj)


class ActivityLog(UUIDModel):
    class Meta:
        constraints = [
            models.CheckConstraint(
                name="must_have_team_or_organization_id",
                check=models.Q(team_id__isnull=False) | models.Q(organization_id__isnull=False),
            ),
        ]
        indexes = [models.Index(fields=["team_id", "scope", "item_id"])]

    team_id = models.PositiveIntegerField(null=True)
    organization_id = models.UUIDField(null=True)
    user = models.ForeignKey("posthog.User", null=True, on_delete=models.SET_NULL)
    was_impersonated = models.BooleanField(null=True)
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
    created_at = models.DateTimeField(default=timezone.now)


common_field_exclusions = [
    "id",
    "uuid",
    "short_id",
    "created_at",
    "created_by",
    "last_modified_at",
    "last_modified_by",
    "updated_at",
    "updated_by",
    "team",
    "team_id",
]


field_exclusions: dict[ActivityScope, list[str]] = {
    "Cohort": [
        "version",
        "pending_version",
        "count",
        "is_calculating",
        "last_calculation",
        "errors_calculating",
    ],
    "Notebook": [
        "text_content",
    ],
    "FeatureFlag": [
        "is_simple_flag",
        "experiment",
        "featureflagoverride",
    ],
    "Person": [
        "distinct_ids",
        "name",
        "is_identified",
        "persondistinctid",
        "cohort",
        "cohortpeople",
        "properties_last_updated_at",
        "properties_last_operation",
        "version",
        "is_user",
    ],
    "Insight": [
        "filters_hash",
        "refreshing",
        "dive_dashboard",
        "type",
        "funnel",
        "layouts",
        "color",
        "order",
        "result",
        "dashboard",
        "last_refresh",
        "saved",
        "is_sample",
        "refresh_attempt",
        "short_id",
        "insightviewed",
        "dashboardtile",
        "caching_states",
    ],
    "EventDefinition": [
        "eventdefinition_ptr_id",
        "_state",
        "deprecated_tags",
        "owner_id",
        "query_usage_30_day",
        "verified_at",
        "verified_by",
        "post_to_slack",
    ],
    "PropertyDefinition": [
        "propertydefinition_ptr_id",
        "_state",
        "deprecated_tags",
        "owner_id",
        "query_usage_30_day",
        "volume_30_day",
        "verified_at",
        "verified_by",
        "post_to_slack",
        "property_type_format",
    ],
    "Team": ["uuid", "updated_at", "api_token", "created_at", "id"],
    "Project": ["id", "created_at"],
}


def describe_change(m: Any) -> Union[str, dict]:
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


def _read_through_relation(relation: models.Manager) -> list[Union[dict, str]]:
    described_models = [describe_change(r) for r in relation.all()]

    if all(isinstance(elem, str) for elem in described_models):
        # definitely a list of strings now but mypy doesn't know that
        described_models = sorted(described_models)  # type: ignore

    return described_models


def safely_get_field_value(instance: models.Model | None, field: str):
    """Helper function to get the value of a field, handling related objects and exceptions."""
    if instance is None:
        return None
    try:
        value = getattr(instance, field, None)
        if isinstance(value, models.Manager):
            value = _read_through_relation(value)
    # If the field is a related field and the related object has been deleted, this will raise an ObjectDoesNotExist
    # exception. We catch this exception and return None, since the related object has been deleted, and we
    # don't need any additional information about it other than the fact that it was deleted.
    except ObjectDoesNotExist:
        value = None
    return value


def changes_between(
    model_type: ActivityScope,
    previous: Optional[models.Model],
    current: Optional[models.Model],
) -> list[Change]:
    """
    Identifies changes between two models by comparing fields.
    Note that this method only really works for models that have a single instance
    and not for models that have a many-to-many relationship with another model.
    """
    changes: list[Change] = []

    if previous is None and current is None:
        # There are no changes between two things that don't exist.
        return changes

    if previous is not None:
        fields = current._meta.get_fields() if current is not None else []
        excluded_fields = field_exclusions.get(model_type, []) + common_field_exclusions
        filtered_fields = [f.name for f in fields if f.name not in excluded_fields]

        for field in filtered_fields:
            left = safely_get_field_value(previous, field)
            right = safely_get_field_value(current, field)

            if field == "tagged_items":
                field = "tags"  # Or the UI needs to be coupled to this internal backend naming.

            if field == "dashboards" and "dashboard_tiles" in filtered_fields:
                # Only process dashboard_tiles when it is present. It supersedes dashboards.
                continue

            if model_type == "Insight" and field == "dashboard_tiles":
                # The API exposes this as dashboards and that's what the activity describers expect.
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
    previous: dict[Any, Any],
    new: dict[Any, Any],
    use_field_exclusions: bool = False,
) -> list[Change]:
    """
    Identifies changes between two dictionaries by comparing fields
    """
    changes: list[Change] = []

    if previous == new:
        return changes

    previous = previous or {}
    new = new or {}

    fields = set(list(previous.keys()) + list(new.keys()))
    if use_field_exclusions:
        fields = fields - set(field_exclusions.get(model_type, [])) - set(common_field_exclusions)

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
    *,
    organization_id: Optional[UUID],
    team_id: int,
    user: Optional[User],
    item_id: Optional[Union[int, str, UUID]],
    scope: str,
    activity: str,
    detail: Detail,
    was_impersonated: Optional[bool],
    force_save: bool = False,
) -> None:
    if was_impersonated and user is None:
        logger.warn(
            "activity_log.failed_to_write_to_activity_log",
            team=team_id,
            organization_id=organization_id,
            scope=scope,
            activity=activity,
            exception=ValueError("Cannot log impersonated activity without a user"),
        )
        return
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
            was_impersonated=was_impersonated,
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
        if settings.TEST:
            # Re-raise in tests, so that we can catch failures in test suites - but keep quiet in production,
            # as we currently don't treat activity logs as critical
            raise


@dataclasses.dataclass(frozen=True)
class ActivityPage:
    total_count: int
    limit: int
    has_next: bool
    has_previous: bool
    results: list[ActivityLog]


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
    item_ids: Optional[list[str]] = None,
    limit: int = 10,
    page: int = 1,
) -> ActivityPage:
    # TODO in follow-up to posthog #8931 selecting specific fields into a return type from this query

    activity_query = (
        ActivityLog.objects.select_related("user").filter(team_id=team_id, scope=scope).order_by("-created_at")
    )

    if item_ids is not None:
        activity_query = activity_query.filter(item_id__in=item_ids)

    return get_activity_page(activity_query, limit, page)


def load_all_activity(scope_list: list[ActivityScope], team_id: int, limit: int = 10, page: int = 1):
    activity_query = (
        ActivityLog.objects.select_related("user").filter(team_id=team_id, scope__in=scope_list).order_by("-created_at")
    )

    return get_activity_page(activity_query, limit, page)
