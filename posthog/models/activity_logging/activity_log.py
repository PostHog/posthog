import json
import dataclasses
from typing import TYPE_CHECKING, Any, Literal, Optional, Union
from uuid import UUID

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db import models, transaction
from django.db.models.signals import post_save
from django.dispatch.dispatcher import receiver
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.utils import ActivityDetailEncoder, UUIDTModel

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)

ActivityScope = Literal[
    "Cohort",
    "FeatureFlag",
    "Person",
    "Group",
    "Insight",
    "Plugin",
    "PluginConfig",
    "HogFunction",
    "HogFlow",
    "DataManagement",
    "EventDefinition",
    "PropertyDefinition",
    "Notebook",
    "Endpoint",
    "Dashboard",
    "Replay",
    "Experiment",
    "ExperimentHoldout",
    "ExperimentSavedMetric",
    "Survey",
    "EarlyAccessFeature",
    "SessionRecordingPlaylist",
    "Comment",
    "Team",
    "Project",
    "ErrorTrackingIssue",
    "DataWarehouseSavedQuery",
    "Organization",
    "OrganizationMembership",
    "Role",
    "UserGroup",
    "BatchExport",
    "BatchImport",
    "Integration",
    "Annotation",
    "Tag",
    "TaggedItem",
    "Subscription",
    "PersonalAPIKey",
    "User",
    "Action",
    "AlertConfiguration",
    "Threshold",
    "AlertSubscription",
    "ExternalDataSource",
    "ExternalDataSchema",
]
ChangeAction = Literal["changed", "created", "deleted", "merged", "split", "exported"]


@dataclasses.dataclass(frozen=True)
class Change:
    type: ActivityScope | str
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
class ActivityContextBase:
    """
    Extend this class in specific implementations to add context-specific fields.
    """

    pass


@dataclasses.dataclass(frozen=True)
class Detail:
    # The display name of the item in question
    name: Optional[str] = None
    # The short_id if it has one
    short_id: Optional[str] = None
    type: Optional[str] = None
    changes: Optional[list[Change]] = None
    trigger: Optional[Trigger] = None
    context: Optional[ActivityContextBase] = None


class ActivityLog(UUIDTModel):
    class Meta:
        constraints = [
            models.CheckConstraint(
                name="must_have_team_or_organization_id",
                check=models.Q(team_id__isnull=False) | models.Q(organization_id__isnull=False),
            ),
        ]
        indexes = [
            models.Index(fields=["team_id", "scope", "item_id"]),
            models.Index(
                fields=["organization_id", "scope", "-created_at"],
                name="idx_alog_org_scope_created_at",
                condition=models.Q(detail__isnull=False) & models.Q(detail__jsonb_typeof="object"),
            ),
            models.Index(
                fields=["organization_id"],
                name="idx_alog_org_detail_exists",
                condition=models.Q(detail__isnull=False) & models.Q(detail__jsonb_typeof="object"),
            ),
            # Used for searching on the detail field, e.g. containing a specific value
            GinIndex(
                name="activitylog_detail_gin",
                fields=["detail"],
                opclasses=["jsonb_ops"],
            ),
            # Used primarily for available_filters queries
            GinIndex(
                name="idx_alog_detail_gin_path_ops",
                fields=["detail"],
                opclasses=["jsonb_path_ops"],
                condition=models.Q(detail__isnull=False),
            ),
            # User-specific filtered queries
            models.Index(
                fields=["team_id", "activity", "scope", "user"],
                name="idx_alog_team_act_scope_usr",
                condition=models.Q(was_impersonated=False) & models.Q(is_system=False),
            ),
            # Advanced activity logs: team-scoped queries with ordering
            models.Index(
                fields=["team_id", "scope", "-created_at"],
                name="idx_alog_team_scope_created",
                condition=models.Q(was_impersonated=False) & models.Q(is_system=False),
            ),
            # Advanced activity logs: team queries with activity filter
            models.Index(
                fields=["team_id", "scope", "activity", "-created_at"],
                name="idx_alog_team_scp_act_crtd",
                condition=models.Q(was_impersonated=False) & models.Q(is_system=False),
            ),
        ]

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


field_with_masked_contents: dict[ActivityScope, list[str]] = {
    "HogFunction": [
        "encrypted_inputs",
    ],
    "Integration": [
        "config",
        "sensitive_config",
    ],
    "BatchImport": [
        "import_config",
    ],
    "Subscription": [
        "target_value",
    ],
    "ExternalDataSource": [
        "job_inputs",
    ],
}

field_name_overrides: dict[ActivityScope, dict[str, str]] = {
    "HogFunction": {
        "execution_order": "priority",
    },
    "Organization": {
        "name": "organization name",
        "enforce_2fa": "two-factor authentication requirement",
        "members_can_invite": "member invitation permissions",
        "members_can_use_personal_api_keys": "personal API key permissions",
        "allow_publicly_shared_resources": "public sharing permissions",
        "is_member_join_email_enabled": "member join email notifications",
        "session_cookie_age": "session cookie age",
        "default_experiment_stats_method": "default experiment stats method",
    },
    "BatchExport": {
        "paused": "enabled",
    },
    "ExternalDataSource": {
        "job_inputs": "configuration",
    },
    "ExternalDataSchema": {
        "should_sync": "enabled",
    },
}

# Fields that prevent activity signal triggering entirely when only these fields change
signal_exclusions: dict[ActivityScope, list[str]] = {
    "AlertConfiguration": [
        "last_checked_at",
        "next_check_at",
        "is_calculating",
        "last_notified_at",
        "last_error_at",
    ],
    "Dashboard": ["last_accessed_at"],
    "PersonalAPIKey": [
        "last_used_at",
    ],
}

field_exclusions: dict[ActivityScope, list[str]] = {
    "Cohort": [
        "version",
        "pending_version",
        "count",
        "is_calculating",
        "last_calculation",
        "last_error_at",
        "errors_calculating",
    ],
    "HogFunction": [
        "bytecode",
        "icon_url",
    ],
    "Notebook": [
        "text_content",
    ],
    "FeatureFlag": [
        "is_simple_flag",
        "experiment",
        "featureflagoverride",
        "usage_dashboard",
        "analytics_dashboards",
    ],
    "Experiment": [
        "feature_flag",
        "exposure_cohort",
        "holdout",
        "saved_metrics",
        "experimenttosavedmetric_set",
    ],
    "ExperimentSavedMetric": [
        "experiments",
        "experimenttosavedmetric_set",
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
    "Team": [
        "uuid",
        "updated_at",
        "created_at",
        "id",
        "secret_api_token",
        "secret_api_token_backup",
        "_old_api_token",
    ],
    "Project": ["id", "created_at"],
    "DataWarehouseSavedQuery": [
        "name",
        "columns",
        "status",
        "external_tables",
        "last_run_at",
        "latest_error",
        "sync_frequency_interval",
        "deleted_name",
    ],
    "Organization": [
        "teams",
        "billing",
        "organization_billing",
        "_billing_plan_details",
        "usage",
        "customer_id",
        "customer_trust_scores",
        "personalization",
        "members",
        "memberships",
        "available_product_features",
        "domain_whitelist",
        "setup_section_2_completed",
        "plugins_access_level",
        "is_hipaa",
        "is_ai_data_processing_approved",
        "never_drop_data",
    ],
    "BatchExport": [
        "latest_runs",
        "last_updated_at",
        "last_paused_at",
        "batchexportrun_set",
        "batchexportbackfill_set",
    ],
    "BatchImport": [
        "lease_id",
        "leased_until",
        "status_message",
        "state",
        "secrets",
        "lease_id",
        "backoff_attempt",
        "backoff_until",
    ],
    "Integration": [
        "sensitive_config",
        "errors",
    ],
    "PersonalAPIKey": [
        "value",
        "secure_value",
        "last_used_at",
    ],
    "User": [
        "password",
        "current_organization_id",
        "current_team_id",
        "temporary_token",
        "distinct_id",
        "partial_notification_settings",
        "anonymize_data",
        "is_email_verified",
        "_billing_plan_details",
        "strapi_id",
    ],
    "AlertConfiguration": [
        "last_checked_at",
        "next_check_at",
        "is_calculating",
        "last_notified_at",
        "last_error_at",
    ],
    "Action": [
        "bytecode",
        "bytecode_error",
        "is_calculating",
        "last_calculated_at",
        "embedding_last_synced_at",
        "embedding_version",
        "last_summarized_at",
        "action_steps",
        "events",
        "plugin_configs",
        "tagged_items",
        "survey",
    ],
    "ExternalDataSource": [
        "connection_id",
        "destination_id",
        "are_tables_created",
    ],
    "ExternalDataSchema": [
        "status",
        "sync_type_config",
        "latest_error",
        "last_synced_at",
    ],
}


def describe_change(m: Any) -> Union[str, dict]:
    # Use lazy imports to avoid circular dependencies
    from posthog.models.dashboard import Dashboard
    from posthog.models.dashboard_tile import DashboardTile

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
        field_obj = instance._meta.get_field(field)

        # For ForeignKey/OneToOneField, always access the ID first to avoid lazy loading
        # throwing malformed UUID validation errors
        if isinstance(field_obj, models.ForeignKey | models.OneToOneField):
            field_id = getattr(instance, f"{field}_id", None)
            if field_id is None:
                return None
            # Ensure field_id is actually an ID, not the object itself
            if hasattr(field_id, "pk"):
                field_id = field_id.pk
            # Only fetch the actual object if we have a valid ID
            related_model = field_obj.related_model
            if isinstance(related_model, type) and issubclass(related_model, models.Model):
                return related_model.objects.get(pk=field_id)  # type: ignore[attr-defined]
            else:
                return field_id

        # For other fields, use normal access
        value = getattr(instance, field, None)
        if isinstance(value, models.Manager):
            value = _read_through_relation(value)
        return value

    # If the field is a related field and the related object has been deleted, this will raise an ObjectDoesNotExist
    # exception. We catch this exception and return None, since the related object has been deleted, and we
    # don't need any additional information about it other than the fact that it was deleted.
    except (ObjectDoesNotExist, FieldDoesNotExist):
        return None


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
        masked_fields = field_with_masked_contents.get(model_type, [])
        filtered_fields = [f for f in fields if f.name not in excluded_fields]
        filtered_field_names = [f.name for f in filtered_fields]

        for field in filtered_fields:
            field_name = field.name
            left = safely_get_field_value(previous, field_name)
            right = safely_get_field_value(current, field_name)

            if field_name == "tagged_items":
                field_name = "tags"  # Or the UI needs to be coupled to this internal backend naming.

            if field_name == "dashboards" and "dashboard_tiles" in filtered_field_names:
                # Only process dashboard_tiles when it is present. It supersedes dashboards.
                continue

            if model_type == "Insight" and field_name == "dashboard_tiles":
                # The API exposes this as dashboards and that's what the activity describers expect.
                field_name = "dashboards"

            # if is a django model field, check the empty_values list
            left_is_none = left is None or (hasattr(field, "empty_values") and left in field.empty_values)
            right_is_none = right is None or (hasattr(field, "empty_values") and right in field.empty_values)

            left_value = "masked" if field_name in masked_fields else left
            right_value = "masked" if field_name in masked_fields else right

            # Use the override name if it exists
            display_name = field_name_overrides.get(model_type, {}).get(field_name, field_name)
            if left_is_none and right_is_none:
                pass  # could be {} vs None
            elif left_is_none and not right_is_none:
                changes.append(Change(type=model_type, field=display_name, action="created", after=right_value))
            elif right_is_none and not left_is_none:
                changes.append(Change(type=model_type, field=display_name, action="deleted", before=left_value))
            elif left != right:
                changes.append(
                    Change(
                        type=model_type,
                        field=display_name,
                        action="changed",
                        before=left_value,
                        after=right_value,
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
    team_id: Optional[int],
    user: Optional["User"],
    item_id: Optional[Union[int, str, UUID]],
    scope: str,
    activity: str,
    detail: Detail,
    was_impersonated: Optional[bool],
    force_save: bool = False,
) -> ActivityLog | None:
    if was_impersonated and user is None:
        logger.warn(
            "activity_log.failed_to_write_to_activity_log",
            team=team_id,
            organization_id=organization_id,
            scope=scope,
            activity=activity,
            exception=ValueError("Cannot log impersonated activity without a user"),
        )
        return None
    try:
        if activity == "updated" and (detail.changes is None or len(detail.changes) == 0) and not force_save:
            logger.warn(
                "activity_log.ignore_update_activity_no_changes",
                team_id=team_id,
                organization_id=organization_id,
                user_id=user.id if user else None,
                scope=scope,
            )
            return None

        def _do_log_activity():
            return ActivityLog.objects.create(
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

        # Check if we're in a transaction, if yes, defer the activity log creation to the commit signal
        if not transaction.get_autocommit() and getattr(settings, "ACTIVITY_LOG_TRANSACTION_MANAGEMENT", True):
            transaction.on_commit(_do_log_activity)
            return None
        else:
            return _do_log_activity()

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

    return None


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


@receiver(post_save, sender=ActivityLog)
def activity_log_created(sender, instance: "ActivityLog", created, **kwargs):
    from posthog.api.advanced_activity_logs import ActivityLogSerializer
    from posthog.api.shared import UserBasicSerializer
    from posthog.cdp.internal_events import InternalEventEvent, InternalEventPerson, produce_internal_event

    try:
        serialized_data = ActivityLogSerializer(instance).data
        # We need to serialize the detail object using the encoder to avoid unsupported types like timedelta
        serialized_data["detail"] = json.loads(json.dumps(serialized_data["detail"], cls=ActivityDetailEncoder))
        # TODO: Move this into the producer to support dataclasses
        user_data = UserBasicSerializer(instance.user).data if instance.user else None

        if created and instance.team_id is not None:
            produce_internal_event(
                team_id=instance.team_id,
                event=InternalEventEvent(
                    event="$activity_log_entry_created",
                    distinct_id=user_data["distinct_id"] if user_data else f"team_{instance.team_id}",
                    properties=serialized_data,
                ),
                person=(
                    InternalEventPerson(
                        id=user_data["id"],
                        properties=user_data,
                    )
                    if user_data
                    else None
                ),
            )
    except Exception as e:
        # We don't want to hard fail here.
        logger.exception("Failed to produce internal event", data=serialized_data, error=e)
        capture_exception(e)
        return
