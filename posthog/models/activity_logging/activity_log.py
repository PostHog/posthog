import json
import dataclasses
from typing import TYPE_CHECKING, Any, Literal, Optional, Required, TypedDict, Union
from uuid import UUID

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist
from django.core.paginator import Paginator
from django.db import models, transaction
from django.db.models import QuerySet
from django.db.models.signals import post_save
from django.dispatch.dispatcher import receiver
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.utils import ACTIVITY_LOG_CLIENT_MAX_LENGTH, activity_storage
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
    "EndpointVersion",
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
    "LegalDocument",
    "Organization",
    "OrganizationDomain",
    "OrganizationMembership",
    "Role",
    "UserGroup",
    "BatchExport",
    "BatchImport",
    "ExportedAsset",
    "Integration",
    "Annotation",
    "Tag",
    "TaggedItem",
    "Subscription",
    "PersonalAPIKey",
    "ProjectSecretAPIKey",
    "OAuthApplication",
    "User",
    "Action",
    "AlertConfiguration",
    "Threshold",
    "AlertSubscription",
    "ExternalDataSource",
    "ExternalDataSchema",
    "Evaluation",
    "LLMTrace",
    "AIGatewayCredit",
    "WebAnalyticsFilterPreset",
    "CustomerProfileConfig",
    "Log",
    "LogsAlertConfiguration",
    "LogsExclusionRule",
    "DashboardWidget",
    "ProductTour",
    "Ticket",
    "InstanceSetting",
    "SignalReport",
    "SignalScoutConfig",
    "StreamlitApp",
    "Metric",
]
ChangeAction = Literal[
    "changed", "created", "deleted", "merged", "split", "exported", "revoked", "logged_in", "logged_out", "copied"
]

# Internal-only scope key. Used by `field_exclusions` and `changes_between` to address
# through-tables and other internal models that are never exposed as a top-level
# `scope` in stored activity logs. Keeping these out of `ActivityScope` prevents them
# from leaking into the generated `ActivityLogListScope` API enum, where filtering by
# them would always return zero results.
InternalActivityScope = Literal["ExperimentToSavedMetric",]
AuditableScope = Union[ActivityScope, InternalActivityScope]


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
                condition=models.Q(team_id__isnull=False) | models.Q(organization_id__isnull=False),
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
    # Value of the x-posthog-client request header captured when the activity was logged
    client = models.CharField(max_length=ACTIVITY_LOG_CLIENT_MAX_LENGTH, null=True, blank=True)
    # Client IP captured at request time. Null for non-HTTP activity (system, Celery).
    ip_address = models.GenericIPAddressField(null=True, blank=True)

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


field_with_masked_contents: dict[AuditableScope, list[str]] = {
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
    "OrganizationDomain": [
        "_scim_bearer_token",
        "verification_challenge",
        "_saml_x509_cert",
    ],
    "User": [
        "email",
        "password",
        # No longer used but kept for backwards-compatibility with existing activity log entries
        "temporary_token",
        "pending_email",
    ],
}

field_name_overrides: dict[AuditableScope, dict[str, str]] = {
    "HogFunction": {
        "execution_order": "priority",
    },
    "Organization": {
        "name": "organization name",
        "enforce_2fa": "two-factor authentication requirement",
        "members_can_invite": "member invitation permissions",
        "members_can_create_projects": "member project creation permissions",
        "members_can_use_personal_api_keys": "personal API key permissions",
        "allow_publicly_shared_resources": "public sharing permissions",
        "is_member_join_email_enabled": "member join email notifications",
        "session_cookie_age": "session cookie age",
        "default_experiment_stats_method": "default experiment stats method",
        "is_ai_data_processing_approved": "third-party AI services",
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
    "SignalScoutConfig": {
        "run_interval_minutes": "run interval (minutes)",
        "emit": "emit findings",
    },
    "OrganizationDomain": {
        "jit_provisioning_enabled": "just-in-time provisioning",
        "sso_enforcement": "SSO enforcement",
        "_saml_entity_id": "SAML entity ID",
        "_saml_acs_url": "SAML ACS URL",
        "_saml_x509_cert": "SAML X.509 certificate",
        "_scim_enabled": "SCIM provisioning",
        "verified_at": "domain verification",
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
    "LogsAlertConfiguration": [
        "next_check_at",
        "last_notified_at",
        "last_checked_at",
        "consecutive_failures",
        "state",
    ],
    "PersonalAPIKey": [
        "last_used_at",
    ],
    "User": [
        "last_login",
        "date_joined",
        "current_organization",
        "current_team",
        "current_organization_id",
        "current_team_id",
    ],
    "OrganizationDomain": [
        "last_verification_retry",
    ],
    "Subscription": [
        "next_delivery_date",
    ],
    # `last_run_at` is written by the scout coordinator on every tick (~every 15 min per scout).
    # When that is the only change, suppress the activity signal entirely so run bookkeeping
    # never spams the audit log.
    "SignalScoutConfig": [
        "last_run_at",
    ],
}

# Activity visibility restrictions - controls which users can see certain activity logs
# Used to hide sensitive activities (e.g., impersonated logins, user account changes) from non-staff users
activity_visibility_restrictions: list[dict[str, Any]] = [
    {
        "scope": "User",
        "activities": ["logged_in", "logged_out"],
        "exclude_when": {"was_impersonated": True},
        "allow_staff": True,
    },
    {
        "scope": "User",
        "activities": ["created", "updated"],
        "exclude_when": {},
        "allow_staff": True,
    },
    {
        "scope": "User",
        "activities": ["scim_provisioned", "scim_replaced", "scim_updated", "scim_deprovisioned"],
        "exclude_when": {},
        "allow_staff": True,
    },
    {
        "scope": "Role",
        "activities": ["scim_provisioned", "scim_replaced", "scim_updated", "scim_deprovisioned"],
        "exclude_when": {},
        "allow_staff": True,
    },
    {
        # Instance-setting changes are staff-only operations and must not leak into the
        # org-scoped activity log endpoints, which are visible to organization admins.
        "scope": "InstanceSetting",
        "activities": ["updated"],
        "exclude_when": {},
        "allow_staff": True,
    },
    {
        # Admin AI-gateway top-ups are staff-only; keep the staff email, credit reason,
        # and wallet balance out of the org-scoped activity log endpoints.
        "scope": "AIGatewayCredit",
        "activities": ["credit_added"],
        "exclude_when": {},
        "allow_staff": True,
    },
]

field_exclusions: dict[AuditableScope, list[str]] = {
    "Metric": [
        # Derived/throttled fields, not user-meaningful change diffs.
        "last_run_at",
        "source_insight_query_hash",
        "referenced_table_names",
    ],
    "OrganizationDomain": [
        "organization",
        "scim_provisioned_users",
        # Internal link to the IdP config mirror; the mirrored fields themselves are already logged
        "identity_provider_config",
    ],
    "Subscription": [
        # Scheduler-derived field; keep it out of user-facing change diffs even when another
        # field changes in the same save (signal_exclusions only governs whether the signal fires).
        "next_delivery_date",
        # FK to a connected Slack integration. The generic field-diff captures the related object,
        # which isn't JSON-serializable for the change detail (same reason FeatureFlag/Experiment
        # exclude their FK relations) — without this, editing a subscription's integration 500s the save.
        "integration",
    ],
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
        "experiment",
        "featureflagoverride",
        "usage_dashboard",
        "analytics_dashboards",
        "flag_evaluation_contexts",
    ],
    "Experiment": [
        "feature_flag",
        "feature_flag_auto_archived",
        "exposure_cohort",
        "holdout",
        "saved_metrics",
        "experimenttosavedmetric_set",
    ],
    "ExperimentSavedMetric": [
        "experiments",
        "experimenttosavedmetric_set",
    ],
    "ExperimentToSavedMetric": [
        "experiment",
        "saved_metric",
    ],
    "ProjectSecretAPIKey": [
        "secure_value",
        # Gateway is team-scoped; resolving it for a diff would hit the fail-closed
        # manager. Binding changes are audited by the gateway management API instead.
        "gateway",
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
        "deleted_name",
    ],
    "Endpoint": [
        "saved_query",
        "current_version",
    ],
    "EndpointVersion": [
        "saved_query",
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
        "last_rolled_at",
    ],
    "User": [
        # ForeignKey fields
        "current_organization",
        "current_team",
        # The onboarding delegation FK is excluded here because the generic field-diffing
        # path tries to serialize the related invite during the signal, which races the
        # same transaction that created the invite. Forensic visibility for delegation
        # state transitions is handled via explicit structlog entries from
        # `set_delegated_state` / `clear_delegation_state` / the pre_delete receiver.
        "onboarding_delegated_to_invite",
        # With _id suffix for direct attribute access
        "current_organization_id",
        "current_team_id",
        "onboarding_delegated_to_invite_id",
        # System/internal fields
        "distinct_id",
        "partial_notification_settings",
        "_billing_plan_details",
        "strapi_id",
        # Reverse relations and many-to-many fields
        "organization",
        "logentry_set",
        "groups",
        "user_permissions",
        "social_auth",
        "organization_memberships",
        "totp_device_set",
        "staticdevice_set",
        "activitylog_set",
        "personal_api_keys",
        "organizations",
        "plugin_set",
        "insightviewed_set",
        "text_set",
        "insight_set",
        "sharingconfiguration_set",
        "exportedasset_set",
        "uploaded_media",
        "accesscontrol_set",
        "rolemembership_set",
        "totp_devices",
        "static_devices",
        "recovery_devices",
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
        # Reverse relation to a fail-closed model: reading through it in `changes_between` raises
        # TeamScopeError when a source is saved outside request scope, and it isn't source-config intent.
        "custom_oauth2_integrations",
    ],
    "ExternalDataSchema": [
        "status",
        "sync_type_config",
        "latest_error",
        "last_synced_at",
    ],
    "Evaluation": [
        # Reverse relations — auto-managed by FK creates, not user intent.
        "reports",
    ],
    "SignalScoutConfig": [
        # Run bookkeeping, not user intent — keep it out of change detection even when it
        # rides along with a real change (belt-and-suspenders with signal_exclusions above).
        "last_run_at",
        # Reverse relations auto-managed by FK creates, not user-initiated config changes.
        "runs",
    ],
    "OAuthApplication": [
        # Secrets — never diff these, even masked.
        "client_secret",
        "hash_client_secret",
        "provisioning_signing_secret",
        # Reverse token relations can hold tens of thousands of rows; reading
        # through them in `changes_between` would scan the token tables.
        "oauthaccesstoken",
        "oauthidtoken",
        "oauthrefreshtoken",
        "oauthgrant",
        # Bookkeeping timestamps and FKs, not scope-ceiling intent.
        "created",
        "updated",
        "cimd_metadata_last_fetched",
        "dcr_client_id_issued_at",
        "organization",
        "user",
    ],
}


def describe_change(m: Any) -> Union[str, dict]:
    # Use lazy imports to avoid circular dependencies
    from products.dashboards.backend.models.dashboard import Dashboard
    from products.dashboards.backend.models.dashboard_tile import DashboardTile

    if isinstance(m, Dashboard):
        return {"id": m.id, "name": m.name}
    if isinstance(m, DashboardTile):
        description: dict[str, Any] = {"dashboard": {"id": m.dashboard.id, "name": m.dashboard.name}}
        description["insight"] = {"id": m.insight_id} if m.insight_id else None
        description["text"] = {"id": m.text_id} if m.text_id else None
        description["button_tile"] = {"id": m.button_tile_id} if m.button_tile_id else None
        description["widget"] = {"id": str(m.widget_id)} if m.widget_id else None
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
    model_type: AuditableScope,
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
    model_type: AuditableScope,
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


def _handle_activity_log_transaction(create_fn, error_context: dict):
    try:
        # Check if we're in a transaction, if yes, defer the activity log creation to the commit signal
        if not transaction.get_autocommit() and getattr(settings, "ACTIVITY_LOG_TRANSACTION_MANAGEMENT", True):
            transaction.on_commit(create_fn)
            return None
        else:
            return create_fn()

    except Exception as e:
        logger.warn(
            "activity_log.failed_to_write_to_activity_log",
            **error_context,
            exception=e,
        )
        capture_exception(e)
        if settings.TEST:
            raise
        return None


def log_activity(
    *,
    organization_id: Optional[UUID],
    team_id: Optional[int],
    user: Optional["User"],
    item_id: Optional[Union[int, str, UUID]],
    scope: str,
    activity: str,
    detail: Detail,
    was_impersonated: bool,
    client: Optional[str] = None,
    ip_address: Optional[str] = None,
    force_save: bool = False,
    instance_only: bool = False,
) -> ActivityLog | None:
    if client is None:
        client = activity_storage.get_client()
    if ip_address is None:
        ip_address = activity_storage.get_ip_address()
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

        def _create_activity_log_instance():
            return ActivityLog(
                organization_id=organization_id,
                team_id=team_id,
                user=user,
                was_impersonated=was_impersonated,
                is_system=user is None,
                item_id=str(item_id),
                scope=scope,
                activity=activity,
                detail=detail,
                client=client,
                ip_address=ip_address,
            )

        def _do_log_activity():
            log = _create_activity_log_instance()
            return ActivityLog.objects.create(
                organization_id=log.organization_id,
                team_id=log.team_id,
                user=log.user,
                was_impersonated=log.was_impersonated,
                is_system=log.is_system,
                item_id=log.item_id,
                scope=log.scope,
                activity=log.activity,
                detail=log.detail,
                client=log.client,
                ip_address=log.ip_address,
            )

        if instance_only:
            return _create_activity_log_instance()

        return _handle_activity_log_transaction(
            _do_log_activity,
            {
                "team": team_id,
                "organization_id": organization_id,
                "scope": scope,
                "activity": activity,
            },
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
        capture_exception(e)
        if settings.TEST:
            raise
        return None


class LogActivityEntry(TypedDict, total=False):
    organization_id: Optional[UUID]
    team_id: Optional[int]
    user: Optional["User"]
    item_id: Optional[Union[int, str, UUID]]
    scope: Required[str]
    activity: Required[str]
    detail: Required[Detail]
    was_impersonated: Required[bool]
    client: Optional[str]
    ip_address: Optional[str]
    force_save: bool


def bulk_log_activity(log_entries: list[LogActivityEntry], batch_size: int = 500) -> list[ActivityLog]:
    if not log_entries:
        return []

    activity_logs = []
    dropped_count = 0
    for entry in log_entries:
        log = log_activity(**entry, instance_only=True)

        if log:
            activity_logs.append(log)
        else:
            dropped_count += 1
            logger.info(
                "bulk_log_activity.entry_dropped",
                scope=entry.get("scope"),
                activity=entry.get("activity"),
                team_id=entry.get("team_id"),
                organization_id=entry.get("organization_id"),
            )

    if dropped_count > 0:
        logger.info(
            "bulk_log_activity.entries_dropped",
            total_entries=len(log_entries),
            dropped_count=dropped_count,
            created_count=len(activity_logs),
        )

    if not activity_logs:
        return []

    def _do_bulk_create():
        created_logs = ActivityLog.objects.bulk_create(activity_logs, batch_size=batch_size)

        for log in created_logs:
            post_save.send(sender=ActivityLog, instance=log, created=True)

        return created_logs

    return (
        _handle_activity_log_transaction(
            _do_bulk_create,
            {
                "count": len(activity_logs),
                "scope": "bulk_log_activity",
                "activity": "bulk_create",
                "log_entries": log_entries,
            },
        )
        or []
    )


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


def apply_activity_visibility_restrictions(queryset: QuerySet, user: Union["User", AnonymousUser, None]) -> QuerySet:
    """
    Apply visibility restrictions to activity log queryset based on user permissions.
    """
    from posthog.models.activity_logging.utils import activity_visibility_manager

    is_staff = bool(user and not isinstance(user, AnonymousUser) and hasattr(user, "is_staff") and user.is_staff)
    return activity_visibility_manager.apply_to_queryset(queryset, is_staff)


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
    from posthog.models.activity_logging.utils import activity_visibility_manager

    if not created:
        return

    try:
        if activity_visibility_manager.is_restricted(instance, restrict_for_staff=True):
            logger.info(
                "Skipping restricted activity log event",
                scope=instance.scope,
                activity=instance.activity,
                team_id=instance.team_id,
                organization_id=instance.organization_id,
            )
            return

        serialized_data = ActivityLogSerializer(instance).data
        # We need to serialize the detail object using the encoder to avoid unsupported types like timedelta
        serialized_data["detail"] = json.loads(json.dumps(serialized_data["detail"], cls=ActivityDetailEncoder))
        # TODO: Move this into the producer to support dataclasses
        user_data = UserBasicSerializer(instance.user).data if instance.user else None

        if instance.team_id is not None:
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
        elif instance.organization_id is not None:
            from posthog.tasks.activity_log import broadcast_activity_log_to_organization

            broadcast_activity_log_to_organization.delay(
                organization_id=instance.organization_id,
                serialized_data=serialized_data,
                user_data=user_data,
            )
    except Exception as e:
        # We don't want to hard fail here.
        logger.exception("Failed to produce internal event", data=serialized_data, error=e)
        capture_exception(e)
        return
