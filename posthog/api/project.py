import math
from functools import cached_property
from typing import Any, Optional, cast

from django.conf import settings
from django.db import transaction
from django.db.models import Model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field, extend_schema_view
from rest_framework import exceptions, filters, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import ProjectBackwardCompatBasicSerializer

# These are imported from team.py for now. They are part of the legacy /api/environments/ surface and are
# expected to move project-side (or to a neutral module) in a later PR once /api/environments/ is retired —
# project.py must NOT depend on team.py at that point. The parity *logic* (config writes, retention check,
# and the team-config actions) is defined locally below rather than imported, so it survives that removal.
from posthog.api.team import (
    TEAM_CONFIG_FIELD_ACCESS_CONTROLLED_FIELDS,
    TEAM_CONFIG_FIELDS,
    TEAM_CONFIG_MEMBER_FIELDS_SET,
    EvaluationContextSuggestionRequestSerializer,
    EvaluationContextSuggestionResponseSerializer,
    TeamCustomerAnalyticsConfigSerializer,
    TeamMarketingAnalyticsConfigSerializer,
    TeamRevenueAnalyticsConfigSerializer,
    TeamSerializer,
    TeamWorkflowsConfigSerializer,
    _default_data_color_theme_id,
    _format_serializer_errors,
    get_or_mint_live_events_token,
    handle_conversations_token_on_update,
    handle_logs_config,
    report_conversations_settings_changes,
    validate_secret_token_generation,
    validate_team_attrs,
)
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.cloud_utils import get_cached_instance_license, is_cloud
from posthog.constants import AvailableFeature
from posthog.decorators import disallow_if_impersonated
from posthog.event_usage import report_user_action
from posthog.geoip import get_geoip_properties
from posthog.helpers.impersonation import is_impersonated
from posthog.models import User
from posthog.models.activity_logging.activity_log import (
    ActivityLog,
    Change,
    Detail,
    dict_changes_between,
    load_activity,
    log_activity,
)
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.event_ingestion_restriction_config import EventIngestionRestrictionConfig
from posthog.models.group_type_mapping import cached_group_types_for_project
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.product_intent.product_intent import (
    ProductIntent,
    ProductIntentSerializer,
    cached_product_intents_for_team,
    enqueue_product_activation_calc_debounced,
)
from posthog.models.project import Project
from posthog.models.team.event_retention import should_enforce_events_retention
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.setup_tasks import SetupTaskId
from posthog.models.team.team import CURRENCY_CODE_CHOICES, Team
from posthog.models.team.util import actions_that_require_current_team
from posthog.models.utils import UUIDT
from posthog.permissions import (
    CREATE_ACTIONS,
    APIScopePermission,
    OrganizationMemberPermissions,
    TeamMemberLightManagementPermission,
    TeamMemberStrictManagementPermission,
    UserCanCreateProjectPermission,
    get_organization_from_view,
)
from posthog.rbac.user_access_control import (
    UserAccessControlSerializerMixin,
    get_field_access_control_map,
    resource_to_display_name,
)
from posthog.scopes import APIScopeObjectOrNotSupported
from posthog.session_recordings.data_retention import (
    VALID_RETENTION_PERIODS,
    parse_feature_to_entitlement,
    retention_violates_entitlement,
    validate_retention_period,
)
from posthog.user_permissions import UserPermissions, UserPermissionsSerializerMixin
from posthog.utils import get_instance_realm, get_ip_address, get_week_start_for_country_code

from products.feature_flags.backend.models import TeamFeatureFlagDefaultsConfig
from products.feature_flags.backend.models.evaluation_context import (
    EvaluationContext,
    TeamDefaultEvaluationContext,
    normalize_context_name,
)
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    TargetType,
    create_notification,
)
from products.signals.backend.models import SignalSourceConfig

from ee.api.rbac.access_control import AccessControlViewSetMixin

logger = structlog.get_logger(__name__)

MAX_ALLOWED_PROJECTS_PER_ORG = 1500


# --- Backward-compatibility logic for the /api/projects/ surface ---
# These mirror the behaviour of the legacy /api/environments/ (TeamViewSet/TeamSerializer) endpoints, operating
# on a project's passthrough Team. They live here — not imported from team.py — so /api/projects/ keeps working
# after /api/environments/ is retired. Until then both surfaces intentionally carry equivalent logic; the
# introspection test in test_team_project_parity.py guards against drift.
def capture_team_config_diff(team: Team, key: str, before: dict, after: dict, *, context: dict) -> None:
    changes = dict_changes_between("Team", {key: before}, {key: after}, use_field_exclusions=True)
    if changes:
        request = context["request"]
        log_activity(
            organization_id=cast(UUIDT, team.organization_id),
            team_id=team.pk,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
            scope="Team",
            item_id=team.pk,
            activity="updated",
            detail=Detail(name=str(team.name), changes=changes),
        )


def update_team_revenue_analytics_config(team: Team, validated_data: dict[str, Any], *, context: dict) -> None:
    user_access_control = context.get("user_access_control")
    old_config = {
        "events": [event.model_dump() for event in (team.revenue_analytics_config.events or [])],
        "goals": [goal.model_dump() for goal in (team.revenue_analytics_config.goals or [])],
        "filter_test_accounts": team.revenue_analytics_config.filter_test_accounts,
    }

    serializer = TeamRevenueAnalyticsConfigSerializer(
        team.revenue_analytics_config,
        data=validated_data,
        partial=True,
        context={**context, "user_access_control": user_access_control},
    )
    if not serializer.is_valid():
        raise serializers.ValidationError(_format_serializer_errors(serializer.errors))

    serializer.save()

    new_config = {
        "events": validated_data.get("events", []),
        "goals": validated_data.get("goals", []),
        "filter_test_accounts": validated_data.get("filter_test_accounts", False),
    }

    capture_team_config_diff(team, "revenue_analytics_config", old_config, new_config, context=context)

    if "events" in validated_data:
        from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet
        from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

        managed_viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
            team=team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )
        managed_viewset.sync_views()


def update_team_marketing_analytics_config(team: Team, validated_data: dict[str, Any], *, context: dict) -> None:
    user_access_control = context.get("user_access_control")
    old_config = {
        "sources_map": (
            team.marketing_analytics_config.sources_map.copy() if team.marketing_analytics_config.sources_map else {}
        ),
        "attribution_window_days": team.marketing_analytics_config.attribution_window_days,
        "attribution_mode": team.marketing_analytics_config.attribution_mode,
    }

    marketing_serializer = TeamMarketingAnalyticsConfigSerializer(
        team.marketing_analytics_config,
        data=validated_data,
        partial=True,
        context={**context, "user_access_control": user_access_control},
    )
    if not marketing_serializer.is_valid():
        raise serializers.ValidationError(_format_serializer_errors(marketing_serializer.errors))

    marketing_serializer.save()

    new_config = {
        "sources_map": validated_data.get("sources_map", {}),
        "attribution_window_days": validated_data.get("attribution_window_days"),
        "attribution_mode": validated_data.get("attribution_mode"),
    }

    capture_team_config_diff(team, "marketing_analytics_config", old_config, new_config, context=context)


def update_team_customer_analytics_config(team: Team, validated_data: dict[str, Any], *, context: dict) -> None:
    user_access_control = context.get("user_access_control")
    old_config = {
        "activity_event": team.customer_analytics_config.activity_event,
        "signup_pageview_event": team.customer_analytics_config.signup_pageview_event,
        "signup_event": team.customer_analytics_config.signup_event,
        "subscription_event": team.customer_analytics_config.subscription_event,
        "payment_event": team.customer_analytics_config.payment_event,
        "account_group_type_index": team.customer_analytics_config.account_group_type_index,
    }

    serializer = TeamCustomerAnalyticsConfigSerializer(
        team.customer_analytics_config,
        data=validated_data,
        partial=True,
        context={**context, "user_access_control": user_access_control},
    )
    if not serializer.is_valid():
        raise serializers.ValidationError(_format_serializer_errors(serializer.errors))

    serializer.save()

    new_config = {
        field: getattr(team.customer_analytics_config, field)
        for field in TeamCustomerAnalyticsConfigSerializer.Meta.fields
    }
    capture_team_config_diff(team, "customer_analytics_config", old_config, new_config, context=context)


def update_team_workflows_config(team: Team, validated_data: dict[str, Any], *, context: dict) -> None:
    user_access_control = context.get("user_access_control")
    old_config = {field: getattr(team.workflows_config, field) for field in TeamWorkflowsConfigSerializer.Meta.fields}

    serializer = TeamWorkflowsConfigSerializer(
        team.workflows_config,
        data=validated_data,
        partial=True,
        context={**context, "user_access_control": user_access_control},
    )
    if not serializer.is_valid():
        raise serializers.ValidationError(_format_serializer_errors(serializer.errors))

    serializer.save()

    new_config = {field: getattr(team.workflows_config, field) for field in TeamWorkflowsConfigSerializer.Meta.fields}
    capture_team_config_diff(team, "workflows_config", old_config, new_config, context=context)


def verify_team_session_recording_retention_period(team: Team, new_retention_period: str) -> None:
    retention_feature = team.organization.get_available_feature(AvailableFeature.SESSION_REPLAY_DATA_RETENTION)
    highest_retention_entitlement = parse_feature_to_entitlement(retention_feature)

    if highest_retention_entitlement is None:
        raise exceptions.APIException(detail="Invalid retention entitlement.")  # HTTP 500

    if not validate_retention_period(new_retention_period):
        raise exceptions.ValidationError(  # HTTP 400
            f"Must provide a valid retention period. Options are: {VALID_RETENTION_PERIODS}."
        )

    if retention_violates_entitlement(new_retention_period, highest_retention_entitlement):
        raise exceptions.PermissionDenied(  # HTTP 403
            f"This organization does not have permission to set retention period of length '{new_retention_period}' - longest allowable retention period is '{highest_retention_entitlement}'."
        )


def team_default_release_conditions_view(team: Team, request: request.Request) -> response.Response:
    """Manage default release conditions for new feature flags in this project."""
    config = get_or_create_team_extension(team, TeamFeatureFlagDefaultsConfig)

    if request.method == "GET":
        return response.Response({"enabled": config.enabled, "default_groups": config.default_groups})

    enabled = request.data.get("enabled", config.enabled)
    default_groups = request.data.get("default_groups", config.default_groups)

    if not isinstance(default_groups, list):
        return response.Response({"error": "default_groups must be a list"}, status=400)

    for i, group in enumerate(default_groups):
        if not isinstance(group, dict):
            return response.Response({"error": f"Group at index {i} must be an object"}, status=400)
        if "properties" not in group or not isinstance(group["properties"], list):
            return response.Response({"error": f"Group at index {i} must have a 'properties' list"}, status=400)
        rollout = group.get("rollout_percentage")
        if rollout is not None and (
            not isinstance(rollout, (int, float)) or math.isnan(rollout) or rollout < 0 or rollout > 100
        ):
            return response.Response(
                {"error": f"Group at index {i} has invalid rollout_percentage (must be 0-100 or null)"}, status=400
            )

    config.enabled = enabled
    config.default_groups = default_groups
    config.save()

    report_user_action(
        request.user,
        "default release conditions updated",
        {"team_id": team.id, "enabled": enabled, "group_count": len(default_groups)},
    )

    return response.Response({"enabled": config.enabled, "default_groups": config.default_groups})


def team_experiments_config_view(team: Team, request: request.Request) -> response.Response:
    """Manage experiment configuration for this project."""
    from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig

    class TeamExperimentsConfigSerializer(serializers.ModelSerializer):
        class Meta:
            model = TeamExperimentsConfig
            fields = [
                "experiment_recalculation_time",
                "default_experiment_confidence_level",
                "default_experiment_stats_method",
                "experiment_precomputation_enabled",
                "default_only_count_matured_users",
                "default_cuped_enabled",
                "default_cuped_lookback_days",
                "default_minimum_detectable_effect",
                "default_sequential_testing_enabled",
                "default_sequential_tuning_parameter",
            ]

    config = get_or_create_team_extension(team, TeamExperimentsConfig)

    if request.method == "PATCH":
        serializer = TeamExperimentsConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response.Response(serializer.data)

    return response.Response(TeamExperimentsConfigSerializer(config).data)


def team_settings_as_of_view(team: Team, request: request.Request) -> response.Response:
    """
    Return the project settings as of the provided timestamp.
    Query params:
    - at: ISO8601 datetime (required)
    - scope: optional, one or multiple keys to filter the returned settings
    """
    at_param = request.query_params.get("at")
    if not at_param:
        raise exceptions.ValidationError({"at": "Query parameter 'at' is required (ISO8601)."})

    as_of = parse_datetime(at_param)
    if as_of is None:
        raise exceptions.ValidationError({"at": "Invalid datetime format. Use ISO8601 (e.g., 2025-11-24T12:34:56Z)."})
    if timezone.is_naive(as_of):
        as_of = timezone.make_aware(as_of)

    settings_fields = set(TEAM_CONFIG_FIELDS)
    snapshot: dict[str, Any] = {}
    for field_name in settings_fields:
        if hasattr(team, field_name):
            snapshot[field_name] = getattr(team, field_name)
        elif hasattr(team, f"{field_name}_id"):
            snapshot[field_name] = getattr(team, f"{field_name}_id")
        else:
            snapshot[field_name] = None

    logs = (
        ActivityLog.objects.filter(team_id=team.id, scope="Team", item_id=str(team.id), created_at__gt=as_of)
        .order_by("-created_at")
        .only("detail", "created_at", "activity")
    )

    for log in logs.iterator():
        detail = log.detail or {}
        changes = detail.get("changes") or []
        for change in changes:
            field = change.get("field")
            action = change.get("action")
            before = change.get("before")

            target = field[:-3] if isinstance(field, str) and field.endswith("_id") else field
            if target not in settings_fields:
                continue

            if action == "changed":
                snapshot[target] = before
            elif action == "created":
                snapshot[target] = None
            elif action == "deleted":
                snapshot[target] = before

    scope_values = request.query_params.getlist("scope")
    if scope_values:
        filtered = {k: snapshot.get(k, None) for k in scope_values}
        return response.Response(filtered)

    return response.Response(snapshot)


def team_event_ingestion_restrictions_view(team: Team, request: request.Request) -> response.Response:
    restrictions = EventIngestionRestrictionConfig.objects.filter(token=team.api_token)
    data = [
        {"restriction_type": restriction.restriction_type, "distinct_ids": restriction.distinct_ids}
        for restriction in restrictions
    ]
    return response.Response(data)


def team_default_evaluation_contexts_view(
    team: Team, request: request.Request, user_permissions: UserPermissions
) -> response.Response:
    """Manage default evaluation contexts for a project."""
    # Feature flags persist contexts under the project root team (RootTeamMixin), so scope
    # context lookups to the root team — otherwise flag-used contexts are invisible from
    # child environments.
    root_team = team.parent_team or team

    if request.method == "GET":
        defaults = TeamDefaultEvaluationContext.objects.filter(team=root_team).select_related("evaluation_context")
        defaults_data = [{"id": d.id, "name": d.evaluation_context.name} for d in defaults]
        all_contexts_qs = list(
            EvaluationContext.objects.filter(team=root_team)
            .values_list("name", "hidden_from_suggestions")
            .order_by("name")
        )
        all_contexts = [name for name, hidden in all_contexts_qs if not hidden]
        hidden_contexts = [name for name, hidden in all_contexts_qs if hidden]
        return response.Response(
            {
                "default_evaluation_contexts": defaults_data,
                "available_contexts": all_contexts,
                "hidden_contexts": hidden_contexts,
                "enabled": team.default_evaluation_contexts_enabled,
            }
        )

    elif request.method == "POST":
        context_name = request.data.get("context_name", "")
        if not isinstance(context_name, str):
            return response.Response({"error": "context_name must be a string"}, status=400)
        context_name = normalize_context_name(context_name)
        if not context_name:
            return response.Response({"error": "context_name is required"}, status=400)
        if len(context_name) > 255:
            return response.Response({"error": "context_name must be at most 255 characters"}, status=400)

        with transaction.atomic():
            existing = list(TeamDefaultEvaluationContext.objects.filter(team=root_team).select_for_update())
            if len(existing) >= 10:
                return response.Response({"error": "Maximum of 10 default evaluation contexts allowed"}, status=400)

            ctx, _ = EvaluationContext.objects.get_or_create(name=context_name, team=root_team)
            if ctx.hidden_from_suggestions:
                level = user_permissions.team(team).effective_membership_level
                if level is not None and level >= OrganizationMembership.Level.ADMIN:
                    ctx.hidden_from_suggestions = False
                    ctx.save(update_fields=["hidden_from_suggestions"])
            default_ctx, created = TeamDefaultEvaluationContext.objects.get_or_create(
                team=root_team, evaluation_context=ctx
            )

            if created:
                report_user_action(
                    cast(User, request.user),
                    "default evaluation context added",
                    {"team_id": team.id, "context_name": context_name},
                    team=team,
                    request=request,
                )

        return response.Response(
            {
                "id": default_ctx.id,
                "name": ctx.name,
                "created": created,
                "hidden_from_suggestions": ctx.hidden_from_suggestions,
            }
        )

    else:  # DELETE
        context_name = request.data.get("context_name", "") or request.GET.get("context_name", "")
        if not isinstance(context_name, str):
            return response.Response({"error": "context_name must be a string"}, status=400)
        context_name = normalize_context_name(context_name)
        if not context_name:
            return response.Response({"error": "context_name is required"}, status=400)

        with transaction.atomic():
            try:
                ctx = EvaluationContext.objects.get(name=context_name, team=root_team)
                deleted_count, _ = TeamDefaultEvaluationContext.objects.filter(
                    team=root_team, evaluation_context=ctx
                ).delete()

                if deleted_count > 0:
                    report_user_action(
                        cast(User, request.user),
                        "default evaluation context removed",
                        {"team_id": team.id, "context_name": context_name},
                        team=team,
                        request=request,
                    )

                return response.Response({"success": True})
            except EvaluationContext.DoesNotExist:
                return response.Response({"error": "Evaluation context not found"}, status=404)


def team_evaluation_context_suggestions_view(team: Team, request: request.Request) -> response.Response:
    """Hide an evaluation context name from the flag editor's suggestion list, or restore it.

    POST hides the name; DELETE restores it. The underlying context row and any flags already
    using it are never modified — this only controls what gets suggested."""
    # Contexts are persisted under the project root team (see team_default_evaluation_contexts_view).
    root_team = team.parent_team or team

    context_name = request.data.get("context_name", "") or request.GET.get("context_name", "")
    if not isinstance(context_name, str):
        return response.Response({"error": "context_name must be a string"}, status=400)
    context_name = normalize_context_name(context_name)
    if not context_name:
        return response.Response({"error": "context_name is required"}, status=400)

    hidden = request.method == "POST"

    with transaction.atomic():
        try:
            ctx = EvaluationContext.objects.select_for_update().get(name=context_name, team=root_team)
        except EvaluationContext.DoesNotExist:
            return response.Response({"error": "Evaluation context not found"}, status=404)

        if ctx.hidden_from_suggestions != hidden:
            ctx.hidden_from_suggestions = hidden
            ctx.save(update_fields=["hidden_from_suggestions"])
            report_user_action(
                cast(User, request.user),
                "evaluation context suggestion hidden" if hidden else "evaluation context suggestion restored",
                {"team_id": team.id, "context_name": context_name},
                team=team,
                request=request,
            )

    return response.Response({"success": True, "name": context_name, "hidden_from_suggestions": hidden})


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        # Keep this serializer narrow; legacy Team-compatible fields live on ProjectBackwardCompatSerializer.
        fields = ["id", "organization_id", "name", "product_description", "created_at", "is_pending_deletion"]
        read_only_fields = ["id", "organization_id", "created_at", "is_pending_deletion"]


class ProjectBackwardCompatSerializer(
    UserAccessControlSerializerMixin,
    ProjectBackwardCompatBasicSerializer,
    UserPermissionsSerializerMixin,
):
    effective_membership_level = serializers.SerializerMethodField()  # Compat with TeamSerializer
    has_group_types = serializers.SerializerMethodField()  # Compat with TeamSerializer
    group_types = serializers.SerializerMethodField()  # Compat with TeamSerializer
    live_events_token = serializers.SerializerMethodField()  # Compat with TeamSerializer
    product_intents = serializers.SerializerMethodField()  # Compat with TeamSerializer
    available_setup_task_ids = serializers.SerializerMethodField()  # Compat with TeamSerializer
    managed_viewsets = serializers.SerializerMethodField()  # Compat with TeamSerializer
    events_retention_enforced = serializers.SerializerMethodField(
        help_text="Whether events data retention is currently enforced for this team (cohort/flag gated)."
    )  # Compat with TeamSerializer
    # These are @property attrs on Team, not Django model fields — declare explicitly so drf-spectacular can resolve them
    default_modifiers = serializers.DictField(read_only=True)  # Compat with TeamSerializer
    person_on_events_querying_enabled = serializers.BooleanField(read_only=True)  # Compat with TeamSerializer
    # project_id mirrors TeamSerializer.project_id; for a Project it equals its own id (Project ↔ Team is 1:1)
    project_id = serializers.IntegerField(
        source="id", read_only=True, help_text="ID of the project this environment belongs to."
    )
    # Analytics config sub-objects live on the passthrough Team — reuse the Team serializers for identical shape
    revenue_analytics_config = TeamRevenueAnalyticsConfigSerializer(required=False)  # Compat with TeamSerializer
    marketing_analytics_config = TeamMarketingAnalyticsConfigSerializer(required=False)  # Compat with TeamSerializer
    customer_analytics_config = TeamCustomerAnalyticsConfigSerializer(required=False)  # Compat with TeamSerializer
    workflows_config = TeamWorkflowsConfigSerializer(required=False)  # Compat with TeamSerializer
    # No `default` on purpose: a default value would be auto-injected into every create payload, which trips the
    # admin-only-fields-on-creation gate in validate_team_attrs and blocks members allowed to create projects.
    base_currency = serializers.ChoiceField(choices=CURRENCY_CODE_CHOICES, required=False)  # Compat with TeamSerializer

    def validate_app_urls(self, value: list[str | None] | None) -> list[str] | None:
        if value is None:
            return value
        return [url for url in value if url]

    def validate_recording_domains(self, value: list[str | None] | None) -> list[str] | None:
        if value is None:
            return value
        return [domain for domain in value if domain]

    def validate_conversations_settings(self, value: dict | None) -> dict | None:
        if value is None:
            return value
        # Filter out None values from widget_domains if present
        if "widget_domains" in value and value["widget_domains"] is not None:
            value["widget_domains"] = [domain for domain in value["widget_domains"] if domain]
        return value

    class Meta:
        model = Project
        fields = (
            "id",
            "organization",
            "name",
            "product_description",
            "created_at",
            "effective_membership_level",  # Compat with TeamSerializer
            "has_group_types",  # Compat with TeamSerializer
            "group_types",  # Compat with TeamSerializer
            "live_events_token",  # Compat with TeamSerializer
            "updated_at",  # Compat with TeamSerializer
            "uuid",  # Compat with TeamSerializer
            "api_token",  # Compat with TeamSerializer
            "app_urls",  # Compat with TeamSerializer
            "anonymize_ips",  # Compat with TeamSerializer
            "completed_snippet_onboarding",  # Compat with TeamSerializer
            "ingested_event",  # Compat with TeamSerializer
            "test_account_filters",  # Compat with TeamSerializer
            "test_account_filters_default_checked",  # Compat with TeamSerializer
            "path_cleaning_filters",  # Compat with TeamSerializer
            "is_demo",  # Compat with TeamSerializer
            "timezone",  # Compat with TeamSerializer
            "data_attributes",  # Compat with TeamSerializer
            "person_display_name_properties",  # Compat with TeamSerializer
            "correlation_config",  # Compat with TeamSerializer
            "autocapture_opt_out",  # Compat with TeamSerializer
            "autocapture_exceptions_opt_in",  # Compat with TeamSerializer
            "autocapture_web_vitals_opt_in",  # Compat with TeamSerializer
            "autocapture_web_vitals_allowed_metrics",  # Compat with TeamSerializer
            "autocapture_exceptions_errors_to_ignore",  # Compat with TeamSerializer
            "capture_console_log_opt_in",  # Compat with TeamSerializer
            "capture_performance_opt_in",  # Compat with TeamSerializer
            "session_recording_opt_in",  # Compat with TeamSerializer
            "session_recording_sample_rate",  # Compat with TeamSerializer
            "session_recording_minimum_duration_milliseconds",  # Compat with TeamSerializer
            "session_recording_linked_flag",  # Compat with TeamSerializer
            "session_recording_network_payload_capture_config",  # Compat with TeamSerializer
            "session_recording_masking_config",  # Compat with TeamSerializer
            "session_recording_url_trigger_config",  # Compat with TeamSerializer
            "session_recording_url_blocklist_config",  # Compat with TeamSerializer
            "session_recording_event_trigger_config",  # Compat with TeamSerializer
            "session_recording_trigger_match_type_config",  # Compat with TeamSerializer
            "session_recording_trigger_groups",  # Compat with TeamSerializer
            "session_recording_retention_period",  # Compat with TeamSerializer
            "session_replay_config",  # Compat with TeamSerializer
            "survey_config",  # Compat with TeamSerializer
            "access_control",  # Compat with TeamSerializer
            "week_start_day",  # Compat with TeamSerializer
            "primary_dashboard",  # Compat with TeamSerializer
            "live_events_columns",  # Compat with TeamSerializer
            "recording_domains",  # Compat with TeamSerializer
            "person_on_events_querying_enabled",  # Compat with TeamSerializer
            "inject_web_apps",  # Compat with TeamSerializer
            "extra_settings",  # Compat with TeamSerializer
            "modifiers",  # Compat with TeamSerializer
            "default_modifiers",  # Compat with TeamSerializer
            "has_completed_onboarding_for",  # Compat with TeamSerializer
            "surveys_opt_in",  # Compat with TeamSerializer
            "heatmaps_opt_in",  # Compat with TeamSerializer
            "product_intents",  # Compat with TeamSerializer
            "flags_persistence_default",  # Compat with TeamSerializer
            "secret_api_token",  # Compat with TeamSerializer
            "secret_api_token_backup",  # Compat with TeamSerializer
            "receive_org_level_activity_logs",  # Compat with TeamSerializer
            "business_model",  # Compat with TeamSerializer
            "conversations_enabled",  # Compat with TeamSerializer
            "conversations_settings",  # Compat with TeamSerializer
            "logs_settings",  # Compat with TeamSerializer
            "proactive_tasks_enabled",  # Compat with TeamSerializer
            "available_setup_task_ids",  # Compat with TeamSerializer
            "is_pending_deletion",
            "project_id",  # Compat with TeamSerializer
            "user_access_level",  # Compat with TeamSerializer
            "managed_viewsets",  # Compat with TeamSerializer
            "revenue_analytics_config",  # Compat with TeamSerializer
            "marketing_analytics_config",  # Compat with TeamSerializer
            "customer_analytics_config",  # Compat with TeamSerializer
            "workflows_config",  # Compat with TeamSerializer
            "base_currency",  # Compat with TeamSerializer
            "capture_dead_clicks",  # Compat with TeamSerializer
            "cookieless_server_hash_mode",  # Compat with TeamSerializer
            "human_friendly_comparison_periods",  # Compat with TeamSerializer
            "feature_flag_confirmation_enabled",  # Compat with TeamSerializer
            "feature_flag_confirmation_message",  # Compat with TeamSerializer
            "default_evaluation_contexts_enabled",  # Compat with TeamSerializer
            "require_evaluation_contexts",  # Compat with TeamSerializer
            "default_data_theme",  # Compat with TeamSerializer
            "onboarding_tasks",  # Compat with TeamSerializer
            "web_analytics_pre_aggregated_tables_enabled",  # Compat with TeamSerializer
            "event_retention_months",  # Compat with TeamSerializer
            "events_retention_enforced",  # Compat with TeamSerializer
        )
        read_only_fields = (
            "id",
            "uuid",
            "organization",
            "is_pending_deletion",
            "effective_membership_level",
            "has_group_types",
            "group_types",
            "live_events_token",
            "created_at",
            "api_token",
            "updated_at",
            "ingested_event",
            "default_modifiers",
            "person_on_events_querying_enabled",
            "product_intents",
            "secret_api_token",
            "secret_api_token_backup",
            "available_setup_task_ids",
            "project_id",
            "user_access_level",
            "managed_viewsets",
            "event_retention_months",
        )

        team_passthrough_fields = {
            "updated_at",
            "uuid",
            "api_token",
            "app_urls",
            "anonymize_ips",
            "completed_snippet_onboarding",
            "ingested_event",
            "test_account_filters",
            "test_account_filters_default_checked",
            "path_cleaning_filters",
            "is_demo",
            "timezone",
            "data_attributes",
            "person_display_name_properties",
            "correlation_config",
            "autocapture_opt_out",
            "autocapture_exceptions_opt_in",
            "autocapture_web_vitals_opt_in",
            "autocapture_web_vitals_allowed_metrics",
            "autocapture_exceptions_errors_to_ignore",
            "capture_console_log_opt_in",
            "capture_performance_opt_in",
            "session_recording_opt_in",
            "session_recording_sample_rate",
            "session_recording_minimum_duration_milliseconds",
            "session_recording_linked_flag",
            "session_recording_network_payload_capture_config",
            "session_recording_masking_config",
            "session_recording_url_trigger_config",
            "session_recording_url_blocklist_config",
            "session_recording_event_trigger_config",
            "session_recording_trigger_match_type_config",
            "session_recording_trigger_groups",
            "session_recording_retention_period",
            "session_replay_config",
            "survey_config",
            "access_control",
            "week_start_day",
            "primary_dashboard",
            "live_events_columns",
            "recording_domains",
            "person_on_events_querying_enabled",
            "inject_web_apps",
            "extra_settings",
            "modifiers",
            "default_modifiers",
            "has_completed_onboarding_for",
            "surveys_opt_in",
            "heatmaps_opt_in",
            "flags_persistence_default",
            "secret_api_token",
            "secret_api_token_backup",
            "receive_org_level_activity_logs",
            "business_model",
            "conversations_enabled",
            "conversations_settings",
            "logs_settings",
            "proactive_tasks_enabled",
            "base_currency",
            "capture_dead_clicks",
            "cookieless_server_hash_mode",
            "human_friendly_comparison_periods",
            "feature_flag_confirmation_enabled",
            "feature_flag_confirmation_message",
            "default_evaluation_contexts_enabled",
            "require_evaluation_contexts",
            "default_data_theme",
            "onboarding_tasks",
            "web_analytics_pre_aggregated_tables_enabled",
            "revenue_analytics_config",
            "marketing_analytics_config",
            "customer_analytics_config",
            "workflows_config",
            "event_retention_months",
        }

        # help_text entries flow into the generated OpenAPI spec, frontend types, and MCP tool schemas.
        # Prioritized for the fields agents most commonly update via the settings endpoint.
        extra_kwargs = {
            "name": {"help_text": "Human-readable project name."},
            "product_description": {
                "help_text": "Short description of what the project is about. This is helpful to give our AI agents context about your project."
            },
            "recording_domains": {
                "help_text": (
                    "Origins permitted to record session replays and heatmaps. Empty list allows all origins."
                )
            },
            "anonymize_ips": {"help_text": "When true, PostHog drops the IP address from every ingested event."},
            "timezone": {
                "help_text": "IANA timezone used for date-based filters and reporting (e.g. `America/Los_Angeles`)."
            },
            "week_start_day": {"help_text": "First day of the week for date range filters. 0 = Sunday, 1 = Monday."},
            "autocapture_opt_out": {"help_text": "Disables posthog-js autocapture (clicks, page views) when true."},
            "autocapture_exceptions_opt_in": {
                "help_text": "Enables automatic capture of JavaScript exceptions via the SDK."
            },
            "autocapture_web_vitals_opt_in": {
                "help_text": "Enables automatic capture of Core Web Vitals performance metrics."
            },
            "capture_console_log_opt_in": {
                "help_text": "Enables capturing browser console logs alongside session replays."
            },
            "capture_performance_opt_in": {"help_text": "Enables capturing performance timing and network requests."},
            "capture_dead_clicks": {"help_text": "Enables capturing clicks that had no effect (rage-click detection)."},
            "heatmaps_opt_in": {"help_text": "Enables heatmap recording on pages that host posthog-js."},
            "surveys_opt_in": {"help_text": "Enables displaying surveys via posthog-js on allowed origins."},
            "session_recording_opt_in": {"help_text": "Enables session replay recording for this project."},
            "session_recording_sample_rate": {
                "help_text": (
                    "Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%)."
                )
            },
            "session_recording_minimum_duration_milliseconds": {
                "help_text": "Skip saving sessions shorter than this many milliseconds."
            },
            "session_recording_retention_period": {
                "help_text": (
                    "How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan)."
                )
            },
            "event_retention_months": {
                "help_text": (
                    "The team's events data retention window in months (plan-derived, synced from billing). When "
                    "retention enforcement is active for the team, queries do not return events older than this many months."
                )
            },
            "data_attributes": {
                "help_text": (
                    "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
                )
            },
            "person_display_name_properties": {
                "help_text": (
                    "Ordered list of person properties used to render a human-friendly display name in the UI."
                )
            },
            "test_account_filters": {
                "help_text": "Filter groups that identify internal/test traffic to be excluded from insights."
            },
            "test_account_filters_default_checked": {
                "help_text": "When true, new insights default to excluding internal/test users."
            },
            "path_cleaning_filters": {
                "help_text": (
                    "Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths."
                )
            },
            "flags_persistence_default": {
                "help_text": "Default value for the `persist` option on newly created feature flags."
            },
            "primary_dashboard": {"help_text": "ID of the dashboard shown as the project's default landing dashboard."},
            "business_model": {
                "help_text": "Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.",
            },
            "conversations_enabled": {
                "help_text": "Enables the customer conversations / live chat product for this project."
            },
        }

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        # Mirror TeamSerializer: fall back to the global default data theme when the color feature isn't available
        if not instance.organization.is_feature_available(AvailableFeature.DATA_COLOR_THEMES):
            representation["default_data_theme"] = _default_data_color_theme_id()
        return representation

    def get_user_access_level(self, obj: Model) -> Optional[str]:
        # The access-control system is keyed on the Team, so resolve through the passthrough Team
        return super().get_user_access_level(cast(Project, obj).passthrough_team)

    @extend_schema_field(serializers.DictField(child=serializers.BooleanField()))
    def get_managed_viewsets(self, obj: Project) -> dict[str, bool]:
        from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet
        from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind

        enabled_set = set(
            DataWarehouseManagedViewSet.objects.filter(team=obj.passthrough_team).values_list("kind", flat=True)
        )
        return {kind: (kind in enabled_set) for kind, _ in DataWarehouseManagedViewSetKind.choices}

    @extend_schema_field(serializers.BooleanField())
    def get_events_retention_enforced(self, obj: Project) -> bool:
        return should_enforce_events_retention(obj.passthrough_team.id)

    @staticmethod
    def validate_revenue_analytics_config(value):
        return TeamSerializer.validate_revenue_analytics_config(value)

    @staticmethod
    def validate_marketing_analytics_config(value):
        return TeamSerializer.validate_marketing_analytics_config(value)

    @staticmethod
    def validate_customer_analytics_config(value):
        return TeamSerializer.validate_customer_analytics_config(value)

    @staticmethod
    def validate_workflows_config(value):
        return TeamSerializer.validate_workflows_config(value)

    def get_effective_membership_level(self, project: Project) -> Optional[OrganizationMembership.Level]:
        team = project.passthrough_team
        return self.user_permissions.team(team).effective_membership_level

    def get_has_group_types(self, project: Project) -> bool:
        return bool(cached_group_types_for_project(project))

    def get_group_types(self, project: Project) -> list[dict[str, Any]]:
        return cached_group_types_for_project(project)

    def get_live_events_token(self, project: Project) -> Optional[str]:
        team = project.passthrough_team
        request = self.context.get("request")
        user_id = request.user.id if request and hasattr(request, "user") and request.user.is_authenticated else None
        return get_or_mint_live_events_token(team, user_id)

    @extend_schema_field(
        {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "product_type": {"type": "string"},
                    "created_at": {"type": "string", "format": "date-time"},
                    "onboarding_completed_at": {"type": "string", "format": "date-time", "nullable": True},
                    "updated_at": {"type": "string", "format": "date-time"},
                },
            },
        }
    )
    def get_product_intents(self, obj):
        # Mirror TeamSerializer.get_product_intents: debounce-then-enqueue rather than
        # .delay() on every render, and read intents from a per-team cache. The old
        # unconditional .delay() did a broker round-trip on every retrieve and would
        # 500 the endpoint when the broker was unavailable.
        team = obj.passthrough_team
        enqueue_product_activation_calc_debounced(team.id)
        return cached_product_intents_for_team(team.id)

    @extend_schema_field(
        serializers.ListField(child=serializers.ChoiceField(choices=[(e.value, e.value) for e in SetupTaskId]))
    )
    def get_available_setup_task_ids(self, obj) -> list[str]:
        return [e.value for e in SetupTaskId]

    def validate_access_control(self, value) -> None:
        return TeamSerializer.validate_access_control(cast(TeamSerializer, self), value)

    @staticmethod
    def validate_session_recording_linked_flag(value) -> dict | None:
        return TeamSerializer.validate_session_recording_linked_flag(value)

    @staticmethod
    def validate_session_recording_network_payload_capture_config(value) -> dict | None:
        return TeamSerializer.validate_session_recording_network_payload_capture_config(value)

    @staticmethod
    def validate_session_recording_masking_config(value) -> dict | None:
        return TeamSerializer.validate_session_recording_masking_config(value)

    @staticmethod
    def validate_session_recording_trigger_groups(value) -> dict | None:
        return TeamSerializer.validate_session_recording_trigger_groups(value)

    @staticmethod
    def validate_session_replay_config(value) -> dict | None:
        return TeamSerializer.validate_session_replay_config(value)

    @staticmethod
    def validate_session_replay_ai_summary_config(value: dict | None) -> dict | None:
        return TeamSerializer.validate_session_replay_ai_summary_config(value)

    def validate_receive_org_level_activity_logs(self, value: bool | None) -> bool | None:
        return TeamSerializer.validate_receive_org_level_activity_logs(cast(TeamSerializer, self), value)

    def validate_logs_settings(self, value: dict | None) -> dict | None:
        return TeamSerializer.validate_logs_settings(cast(TeamSerializer, self), value)

    @staticmethod
    def validate_modifiers(value: dict | None) -> dict | None:
        return TeamSerializer.validate_modifiers(value)

    @staticmethod
    def validate_test_account_filters(value: object) -> list[dict[str, object]]:
        return TeamSerializer.validate_test_account_filters(value)

    def validate_proactive_tasks_enabled(self, value: bool | None) -> bool | None:
        return TeamSerializer.validate_proactive_tasks_enabled(cast(TeamSerializer, self), value)

    def validate(self, attrs: Any) -> Any:
        attrs = validate_team_attrs(attrs, self.context["view"], self.instance)

        if self.instance:
            field_mappings = get_field_access_control_map(Team)
            user_access_control = self.user_access_control
            if field_mappings and user_access_control is not None:
                team = self.instance.passthrough_team
                for field_name in attrs:
                    if field_name not in field_mappings:
                        continue
                    resource, required_level = field_mappings[field_name]
                    if resource == "project":
                        has_access = user_access_control.check_access_level_for_object(team, required_level)
                    else:
                        has_access = user_access_control.check_access_level_for_resource(resource, required_level)
                    if not has_access:
                        display_name = resource_to_display_name(resource)
                        raise serializers.ValidationError(
                            {field_name: f"You need {required_level} access to {display_name} to modify this field."}
                        )
        return super().validate(attrs)

    def create(self, validated_data: dict[str, Any], **kwargs) -> Project:
        # Analytics config sub-objects are created with the Team's defaults and only mutated via update;
        # drop any provided at creation so they don't reach create_with_team (matches TeamSerializer.create).
        for config_field in (
            "revenue_analytics_config",
            "marketing_analytics_config",
            "customer_analytics_config",
            "workflows_config",
        ):
            validated_data.pop(config_field, None)

        serializers.raise_errors_on_nested_writes("create", self, validated_data)
        request = self.context["request"]

        if "week_start_day" not in validated_data:
            country_code = get_geoip_properties(get_ip_address(request)).get("$geoip_country_code", None)
            if country_code:
                week_start_day_for_user_ip_location = get_week_start_for_country_code(country_code)
                # get_week_start_for_country_code() also returns 6 for countries where the week starts on Saturday,
                # but ClickHouse doesn't support Saturday as the first day of the week, so we fall back to Sunday
                validated_data["week_start_day"] = 1 if week_start_day_for_user_ip_location == 1 else 0

        team_fields: dict[str, Any] = {}
        for field_name in validated_data.copy():  # Copy to avoid iterating over a changing dict
            if field_name in self.Meta.team_passthrough_fields:
                team_fields[field_name] = validated_data.pop(field_name)
        project, team = Project.objects.create_with_team(
            organization_id=self.context["view"].organization_id,
            initiating_user=self.context["request"].user,
            **validated_data,
            team_fields=team_fields,
        )

        request.user.current_team = team
        request.user.team = request.user.current_team  # Update cached property
        request.user.save()

        log_activity(
            organization_id=project.organization_id,
            team_id=project.pk,
            user=request.user,
            was_impersonated=is_impersonated(request),
            scope="Project",
            item_id=project.pk,
            activity="created",
            detail=Detail(name=str(project.name)),
        )
        log_activity(
            organization_id=project.organization_id,
            team_id=team.pk,
            user=request.user,
            was_impersonated=is_impersonated(request),
            scope="Team",
            item_id=team.pk,
            activity="created",
            detail=Detail(name=str(team.name)),
        )

        return project

    def update(self, instance: Project, validated_data: dict[str, Any]) -> Project:
        team = instance.passthrough_team
        team_before_update = team.__dict__.copy()
        project_before_update = instance.__dict__.copy()

        # Analytics configs live on related models, not Team columns — handle them via the shared helpers
        # (the same ones TeamSerializer uses) before the generic passthrough loop, and keep them out of it.
        config_context = {**self.context, "user_access_control": self.user_access_control}
        if config_data := validated_data.pop("revenue_analytics_config", None):
            update_team_revenue_analytics_config(team, config_data, context=config_context)
        if config_data := validated_data.pop("marketing_analytics_config", None):
            update_team_marketing_analytics_config(team, config_data, context=config_context)
        if config_data := validated_data.pop("customer_analytics_config", None):
            update_team_customer_analytics_config(team, config_data, context=config_context)
        if config_data := validated_data.pop("workflows_config", None):
            update_team_workflows_config(team, config_data, context=config_context)

        if "session_recording_retention_period" in validated_data:
            verify_team_session_recording_retention_period(team, validated_data["session_recording_retention_period"])

        if "survey_config" in validated_data:
            if team.survey_config is not None and validated_data.get("survey_config") is not None:
                validated_data["survey_config"] = {
                    **team.survey_config,
                    **validated_data["survey_config"],
                }

            if validated_data.get("survey_config") is None:
                del team_before_update["survey_config"]

            survey_config_changes_between = dict_changes_between(
                "Survey",
                team_before_update.get("survey_config", {}),
                validated_data.get("survey_config", {}),
                use_field_exclusions=True,
            )
            if survey_config_changes_between:
                log_activity(
                    organization_id=cast(UUIDT, instance.organization_id),
                    team_id=instance.pk,
                    user=cast(User, self.context["request"].user),
                    was_impersonated=is_impersonated(self.context["request"]),
                    scope="Survey",
                    item_id="#",
                    activity="updated",
                    detail=Detail(
                        name="global survey appearance",
                        changes=survey_config_changes_between,
                    ),
                )

        if (
            "session_replay_config" in validated_data
            and validated_data["session_replay_config"] is not None
            and team.session_replay_config is not None
        ):
            # for session_replay_config and its top level keys we merge existing settings with new settings
            # this way we don't always have to receive the entire settings object to change one setting
            # so for each key in validated_data["session_replay_config"] we merge it with the existing settings
            # and then merge any top level keys that weren't provided

            for key, value in validated_data["session_replay_config"].items():
                if key in team.session_replay_config:
                    # if they're both dicts then we merge them, otherwise, the new value overwrites the old
                    if isinstance(team.session_replay_config[key], dict) and isinstance(
                        validated_data["session_replay_config"][key], dict
                    ):
                        validated_data["session_replay_config"][key] = {
                            **team.session_replay_config[key],  # existing values
                            **value,  # and new values on top
                        }

            # then also add back in any keys that exist but are not in the provided data
            validated_data["session_replay_config"] = {
                **team.session_replay_config,
                **validated_data["session_replay_config"],
            }

        # Merge modifiers with existing values so that updating one modifier doesn't wipe out others
        if "modifiers" in validated_data and validated_data["modifiers"] is not None:
            validated_data["modifiers"] = {
                **(team.modifiers or {}),
                **validated_data["modifiers"],
            }

        # Merge conversations_settings with existing values, unless explicitly clearing with null
        if "conversations_settings" in validated_data and validated_data["conversations_settings"] is not None:
            existing_settings = team.conversations_settings or {}
            new_settings = validated_data["conversations_settings"]
            validated_data["conversations_settings"] = {**existing_settings, **new_settings}

        validated_data = handle_conversations_token_on_update(
            validated_data, team.conversations_enabled, team.conversations_settings
        )

        should_team_be_saved_too = False
        for attr, value in validated_data.items():
            if attr not in self.Meta.team_passthrough_fields:
                # This attr is a Project field
                setattr(instance, attr, value)
            else:
                # This attr is actually on the Project's passthrough Team
                should_team_be_saved_too = True
                setattr(team, attr, value)

        if "name" in validated_data:
            # Keep Team.name mirroring Project.name: surfaces like the organization's teams
            # list and the app context still read the name off the Team row
            should_team_be_saved_too = True
            team.name = validated_data["name"]

        instance.save()
        if should_team_be_saved_too:
            team.save()

        if "proactive_tasks_enabled" in validated_data:
            if validated_data["proactive_tasks_enabled"]:
                SignalSourceConfig.objects.get_or_create(
                    team=team,
                    source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
                    source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
                    defaults={"enabled": True, "config": {}, "created_by": self.context["request"].user},
                )
            else:
                SignalSourceConfig.objects.filter(
                    team=team,
                    source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
                    source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
                ).delete()

        team_after_update = team.__dict__.copy()
        project_after_update = instance.__dict__.copy()
        team_changes = dict_changes_between("Team", team_before_update, team_after_update, use_field_exclusions=True)
        project_changes = dict_changes_between(
            "Project", project_before_update, project_after_update, use_field_exclusions=True
        )

        if team_changes:
            log_activity(
                organization_id=cast(UUIDT, instance.organization_id),
                team_id=instance.pk,
                user=cast(User, self.context["request"].user),
                was_impersonated=is_impersonated(self.context["request"]),
                scope="Team",
                item_id=instance.pk,
                activity="updated",
                detail=Detail(
                    name=str(team.name),
                    changes=team_changes,
                ),
            )
        if project_changes:
            log_activity(
                organization_id=cast(UUIDT, instance.organization_id),
                team_id=instance.pk,
                user=cast(User, self.context["request"].user),
                was_impersonated=is_impersonated(self.context["request"]),
                scope="Project",
                item_id=instance.pk,
                activity="updated",
                detail=Detail(
                    name=str(instance.name),
                    changes=project_changes,
                ),
            )

        report_conversations_settings_changes(
            cast(User, self.context["request"].user),
            team_before_update.get("conversations_settings"),
            team,
        )

        return instance


@extend_schema(extensions={"x-product": "core"})
@extend_schema_view(
    retrieve=extend_schema(
        description=("Retrieve a project and its settings."),
    ),
    update=extend_schema(
        description=(
            "Replace a project and its settings. Prefer the PATCH endpoint for partial updates — PUT requires every "
            "writable field to be provided."
        ),
    ),
    partial_update=extend_schema(
        description=(
            "Update one or more of a project's settings. Only the fields included in the request body are changed."
        ),
    ),
)
class ProjectViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    """
    Projects for the current organization.
    """

    scope_object: APIScopeObjectOrNotSupported = "project"
    serializer_class = ProjectBackwardCompatSerializer
    queryset = Project.objects.all().select_related("organization").prefetch_related("teams")
    lookup_field = "id"
    ordering = "-created_by"
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]

    def safely_get_queryset(self, queryset):
        # IMPORTANT: This is actually what ensures that a user cannot read/update a project for which they don't have permission
        visible_teams_ids = UserPermissions(cast(User, self.request.user)).team_ids_visible_for_user
        queryset = queryset.filter(id__in=visible_teams_ids)
        if isinstance(self.request.successful_authenticator, PersonalAPIKeyAuthentication):
            if scoped_organizations := self.request.successful_authenticator.personal_api_key.scoped_organizations:
                queryset = queryset.filter(organization_id__in=scoped_organizations)
        if isinstance(self.request.successful_authenticator, OAuthAccessTokenAuthentication):
            if scoped_organizations := self.request.successful_authenticator.access_token.scoped_organizations:
                queryset = queryset.filter(organization_id__in=scoped_organizations)
        return queryset.filter(id__in=visible_teams_ids)

    def get_serializer_class(self) -> type[serializers.BaseSerializer]:
        if self.action == "list":
            return ProjectBackwardCompatBasicSerializer
        return super().get_serializer_class()

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        super().perform_create(serializer)
        project = cast(Project, serializer.instance)
        self._notify_org_admins_of_member_project_creation(project)

    def _notify_org_admins_of_member_project_creation(self, project: Project) -> None:
        """When a member (below admin) creates a project, notify org admins/owners in-app. Best-effort."""
        try:
            user = cast(User, self.request.user)
            membership = OrganizationMembership.objects.filter(
                user=user, organization_id=project.organization_id
            ).first()
            if membership is None or membership.level >= OrganizationMembership.Level.ADMIN:
                return

            admin_user_ids = OrganizationMembership.objects.filter(
                organization_id=project.organization_id,
                level__gte=OrganizationMembership.Level.ADMIN,
            ).values_list("user_id", flat=True)

            creator = user.first_name or user.email
            for admin_user_id in admin_user_ids:
                create_notification(
                    NotificationData(
                        team_id=project.pk,
                        notification_type=NotificationType.PROJECT_CREATED,
                        title=f"{creator} created a new project",
                        body=f'"{project.name}" was created by {creator}. Review it in project settings.',
                        target_type=TargetType.USER,
                        target_id=str(admin_user_id),
                        source_url=f"/project/{project.pk}/settings",
                    )
                )
        except Exception:
            logger.exception("Failed to dispatch member project creation notification", project_id=project.pk)

    def dangerously_get_required_scopes(self, request, view) -> list[str] | None:
        # Used for the AccessControlViewSetMixin
        mixin_result = super().dangerously_get_required_scopes(request, view)
        if mixin_result is not None:
            return mixin_result

        # See TeamViewSet.dangerously_get_required_scopes for the rationale. Only downgrade to
        # project:read when every field is member-safe or carries its own field-level access control;
        # anything else falls through to project:write so admin-only settings require admin object access.
        if self.action == "partial_update":
            is_session_auth = isinstance(request.successful_authenticator, SessionAuthentication)
            if is_session_auth:
                request_fields = set(request.data.keys())
                downgradable_fields = TEAM_CONFIG_MEMBER_FIELDS_SET | TEAM_CONFIG_FIELD_ACCESS_CONTROLLED_FIELDS
                if request_fields and request_fields.issubset(downgradable_fields):
                    return ["project:read"]

        # Team-level config actions that any member should be able to edit via the UI.
        # Only downgrade for session auth to preserve read-only API key semantics.
        if self.action in ("default_release_conditions", "default_evaluation_contexts"):
            is_session_auth = isinstance(request.successful_authenticator, SessionAuthentication)
            if is_session_auth:
                return ["project:read"]

        # Fall back to the default behavior
        return None

    # NOTE: Team permissions are somewhat complex so we override the underlying viewset's get_permissions method
    def dangerously_get_permissions(self) -> list:
        """
        Special permissions handling for create requests as the organization is inferred from the current user.
        """

        permissions: list = [
            IsAuthenticated,
            APIScopePermission,
            PremiumMultiProjectPermission,
            *self.permission_classes,
        ]

        # Return early for non-actions (e.g. OPTIONS)
        if self.action:
            if self.action == "create":
                if "is_demo" not in self.request.data or not self.request.data["is_demo"]:
                    permissions.append(UserCanCreateProjectPermission)
                else:
                    permissions.append(OrganizationMemberPermissions)
            elif self.action != "list":
                # Skip TeamMemberAccessPermission for list action, as list is serialized with limited TeamBasicSerializer
                permissions.append(TeamMemberLightManagementPermission)

        return [permission() for permission in permissions]

    def safely_get_object(self, queryset):
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@current":
            team = getattr(self.request.user, "team", None)
            if team is None:
                raise exceptions.NotFound()
            return team.project

        filter_kwargs = {self.lookup_field: lookup_value}
        try:
            project = get_object_or_404(queryset, **filter_kwargs)
        except ValueError as error:
            raise exceptions.ValidationError(str(error))
        return project

    # :KLUDGE: Exposed for compatibility reasons for permission classes.
    @property
    def team(self):
        project = self.get_object()
        return project.teams.get(id=project.id)

    def perform_destroy(self, project: Project):
        from ee.billing.billing_manager import BillingManager

        # Check if bulk deletion operations are disabled via environment variable
        # Projects contain teams, so we need to block project deletion too
        if settings.DISABLE_BULK_DELETES:
            raise exceptions.ValidationError(
                "Project deletion is temporarily disabled during database migration. Please try again later."
            )

        if project.is_pending_deletion:
            raise exceptions.ValidationError("This project is already being deleted.")

        # Block deletion of the last project in an org with an active subscription (cloud only).
        # Fail open if the billing service is unreachable — a 500 here would create a worse stuck state.
        is_last_project = project.organization.projects.count() == 1
        license = get_cached_instance_license()
        try:
            has_active_subscription = (
                settings.EE_AVAILABLE
                and is_cloud()
                and license
                and BillingManager(license).get_billing(project.organization).get("has_active_subscription")
            )
        except Exception:
            logger.exception("Failed to check billing status before project deletion; allowing deletion to proceed")
            has_active_subscription = False

        if is_last_project and has_active_subscription:
            raise exceptions.ValidationError(
                "Cannot delete the last project in an organization with an active subscription. "
                "Please cancel your subscription first in the billing page."
            )

        project_id = project.pk
        organization_id = project.organization_id
        project_name = project.name

        user = cast(User, self.request.user)

        teams = list(project.teams.only("id", "uuid", "name", "organization_id").all())
        team_ids = [team.id for team in teams]

        # Mark as pending deletion so the UI locks this project out until the async task removes it.
        project.is_pending_deletion = True
        project.save(update_fields=["is_pending_deletion"])

        # Hand off all deletion work (bulky postgres, batch exports, project/team records,
        # ClickHouse, email) to the durable Temporal workflow.
        from posthog.temporal.delete_teams.dispatch import start_delete_project_data_workflow

        start_delete_project_data_workflow(
            team_ids=team_ids,
            project_id=project_id,
            user_id=user.id,
            project_name=project_name,
        )

        for team in teams:
            log_activity(
                organization_id=cast(UUIDT, organization_id),
                team_id=team.pk,
                user=user,
                was_impersonated=is_impersonated(self.request),
                scope="Team",
                item_id=team.pk,
                activity="deleted",
                detail=Detail(name=str(team.name)),
            )
            report_user_action(user, "team deleted", team=team, request=self.request)
        log_activity(
            organization_id=cast(UUIDT, organization_id),
            team_id=project_id,
            user=user,
            was_impersonated=is_impersonated(self.request),
            scope="Project",
            item_id=project_id,
            activity="deleted",
            detail=Detail(name=str(project_name)),
        )
        report_user_action(
            user,
            "project deleted",
            {"project_name": project_name},
            team=teams[0],
            request=self.request,
        )

    @action(
        methods=["PATCH"],
        detail=True,
        # Only ADMIN or higher users are allowed to access this project
        permission_classes=[TeamMemberStrictManagementPermission],
    )
    def reset_token(self, request: request.Request, id: str, **kwargs) -> response.Response:
        project = self.get_object()
        project.passthrough_team.reset_token_and_save(
            user=request.user, is_impersonated_session=is_impersonated(request)
        )
        return response.Response(ProjectBackwardCompatSerializer(project, context=self.get_serializer_context()).data)

    @action(
        methods=["PATCH"],
        detail=True,
        # Only ADMIN or higher users are allowed to access this project
        permission_classes=[TeamMemberStrictManagementPermission],
    )
    def rotate_secret_token(self, request: request.Request, id: str, **kwargs) -> response.Response:
        project = self.get_object()
        validate_secret_token_generation(project.passthrough_team, cast(User, request.user))
        project.passthrough_team.rotate_secret_token_and_save(
            user=request.user, is_impersonated_session=is_impersonated(request)
        )
        return response.Response(ProjectBackwardCompatSerializer(project, context=self.get_serializer_context()).data)

    @action(
        methods=["PATCH"],
        detail=True,
        # Only ADMIN or higher users are allowed to access this project
        permission_classes=[TeamMemberStrictManagementPermission],
    )
    def delete_secret_token_backup(self, request: request.Request, id: str, **kwargs) -> response.Response:
        project = self.get_object()
        project.passthrough_team.delete_secret_token_backup_and_save(
            user=request.user, is_impersonated_session=is_impersonated(request)
        )
        return response.Response(ProjectBackwardCompatSerializer(project, context=self.get_serializer_context()).data)

    @action(
        methods=["POST"],
        detail=True,
        permission_classes=[TeamMemberStrictManagementPermission],
    )
    def generate_conversations_public_token(self, request: request.Request, id: str, **kwargs) -> response.Response:
        project = self.get_object()
        project.passthrough_team.generate_conversations_public_token_and_save(
            user=request.user, is_impersonated_session=is_impersonated(request)
        )
        return response.Response(ProjectBackwardCompatSerializer(project, context=self.get_serializer_context()).data)

    @action(
        methods=["GET"],
        detail=True,
        permission_classes=[IsAuthenticated],
    )
    def is_generating_demo_data(self, request: request.Request, id: str, **kwargs) -> response.Response:
        project = self.get_object()
        return response.Response({"is_generating_demo_data": project.passthrough_team.get_is_generating_demo_data()})

    @action(
        methods=["GET", "PATCH"],
        detail=True,
        permission_classes=[TeamMemberLightManagementPermission],
        url_path="logs_config",
    )
    def logs_config(self, request: request.Request, id: str, **kwargs) -> response.Response:
        """Manage logs product configuration for this project's canonical environment.
        Mirrors the env-router action so /api/projects/:id/logs_config/ resolves
        alongside the legacy /api/environments/:id/logs_config/ alias."""
        project = self.get_object()
        return handle_logs_config(request, project.passthrough_team)

    @action(methods=["GET"], detail=True)
    def activity(self, request: request.Request, **kwargs):
        # TODO: This is currently the same as in TeamViewSet - we should rework for the Project scope
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        project = self.get_object()

        activity_page = load_activity(
            scope="Team",
            team_id=project.pk,
            item_ids=[str(project.pk)],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)

    # The following actions mirror TeamViewSet, operating on the project's passthrough Team. They delegate to
    # the shared team_*_view helpers so /api/projects/ and /api/environments/ cannot drift apart.
    @action(
        methods=["GET", "PUT"],
        detail=True,
        permission_classes=[TeamMemberLightManagementPermission],
        url_path="default_release_conditions",
    )
    def default_release_conditions(self, request: request.Request, id: str, **kwargs) -> response.Response:
        """Manage default release conditions for new feature flags in this project."""
        return team_default_release_conditions_view(self.get_object().passthrough_team, request)

    @action(
        methods=["GET", "PATCH"],
        detail=True,
        permission_classes=[TeamMemberStrictManagementPermission],
        url_path="experiments_config",
    )
    def experiments_config(self, request: request.Request, id: str, **kwargs) -> response.Response:
        """Manage experiment configuration for this project."""
        return team_experiments_config_view(self.get_object().passthrough_team, request)

    @action(
        methods=["GET", "POST", "DELETE"],
        detail=True,
        permission_classes=[IsAuthenticated],
    )
    def default_evaluation_contexts(self, request: request.Request, id: str, **kwargs) -> response.Response:
        """Manage default evaluation contexts for a project."""
        return team_default_evaluation_contexts_view(self.get_object().passthrough_team, request, self.user_permissions)

    @extend_schema(
        methods=["POST"],
        request=EvaluationContextSuggestionRequestSerializer,
        responses={200: EvaluationContextSuggestionResponseSerializer},
        extensions={"x-product": "feature_flags"},
    )
    @extend_schema(
        methods=["DELETE"],
        parameters=[
            OpenApiParameter(
                name="context_name",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Name of the evaluation context to restore to suggestions.",
            )
        ],
        responses={200: EvaluationContextSuggestionResponseSerializer},
        extensions={"x-product": "feature_flags"},
    )
    @action(
        methods=["POST", "DELETE"],
        detail=True,
        permission_classes=[TeamMemberStrictManagementPermission],
    )
    def evaluation_context_suggestions(self, request: request.Request, id: str, **kwargs) -> response.Response:
        """Hide an evaluation context name from the flag editor's suggestion list, or restore it.

        POST hides the name; DELETE restores it. The underlying context row and any flags already
        using it are never modified — this only controls what gets suggested.
        """
        return team_evaluation_context_suggestions_view(self.get_object().passthrough_team, request)

    @action(methods=["GET"], detail=True)
    def settings_as_of(self, request: request.Request, **kwargs) -> response.Response:
        """
        Return the project settings as of the provided timestamp.
        Query params:
        - at: ISO8601 datetime (required)
        - scope: optional, one or multiple keys to filter the returned settings
        """
        return team_settings_as_of_view(self.get_object().passthrough_team, request)

    @action(methods=["GET"], detail=True, required_scopes=["project:read"], url_path="event_ingestion_restrictions")
    def event_ingestion_restrictions(self, request, **kwargs):
        return team_event_ingestion_restrictions_view(self.get_object().passthrough_team, request)

    @action(
        methods=["PATCH"],
        detail=True,
        required_scopes=["project:read"],
    )
    @disallow_if_impersonated(message="Impersonated sessions cannot set product intents.")
    def add_product_intent(self, request: request.Request, *args, **kwargs):
        project = self.get_object()
        team = project.passthrough_team
        user = request.user
        current_url = request.headers.get("Referer")
        session_id = request.headers.get("X-Posthog-Session-Id")

        serializer = ProductIntentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ProductIntent.register(
            team=team,
            product_type=serializer.validated_data["product_type"],
            context=serializer.validated_data.get("intent_context"),
            user=cast(User, user),
            metadata={**serializer.validated_data["metadata"], "$current_url": current_url, "$session_id": session_id},
            is_onboarding=False,
        )

        return response.Response(TeamSerializer(team, context=self.get_serializer_context()).data, status=201)

    @action(
        methods=["PATCH"],
        detail=True,
        required_scopes=["project:read"],
    )
    @disallow_if_impersonated(message="Impersonated sessions cannot set product intents.")
    def complete_product_onboarding(self, request: request.Request, *args, **kwargs):
        project = self.get_object()
        team = project.passthrough_team
        user = request.user
        current_url = request.headers.get("Referer")
        session_id = request.headers.get("X-Posthog-Session-Id")

        product_type = cast(ProductKey | None, request.data.get("product_type"))
        if not product_type:
            return response.Response({"error": "product_type is required"}, status=400)
        elif product_type not in ProductKey:
            return response.Response({"error": f"invalid product_type, expected one of {list(ProductKey)}"}, status=400)

        product_intent_serializer = ProductIntentSerializer(data=request.data)
        product_intent_serializer.is_valid(raise_exception=True)
        intent_data = product_intent_serializer.validated_data
        intent_context = intent_data.get("intent_context")

        product_intent = ProductIntent.register(
            team=team,
            product_type=product_type,
            context=intent_context,
            user=cast(User, user),
            metadata={**intent_data["metadata"], "$current_url": current_url, "$session_id": session_id},
            is_onboarding=True,
        )

        if isinstance(user, User):  # typing
            report_user_action(
                user,
                "product onboarding completed",
                {
                    "product_key": product_type,
                    "intent_context": intent_context,
                    "intent_created_at": product_intent.created_at,
                    "intent_updated_at": product_intent.updated_at,
                    "realm": get_instance_realm(),
                },
                team=team,
                request=request,
            )

        return response.Response(TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(methods=["POST"], detail=True)
    def change_organization(self, request: request.Request, id: str, **kwargs) -> response.Response:
        project = self.get_object()
        user = cast(User, request.user)

        target_organization_id = request.data.get("organization_id")
        current_organization = project.organization

        try:
            target_organization = Organization.objects.get(pk=target_organization_id)
            current_organization_membership = OrganizationMembership.objects.get(
                user=user, organization=current_organization
            )
            target_organization_membership = OrganizationMembership.objects.get(
                user=user, organization=target_organization
            )

            if (
                current_organization_membership.level < OrganizationMembership.Level.ADMIN
                or target_organization_membership.level < OrganizationMembership.Level.ADMIN
            ):
                raise exceptions.ValidationError(
                    "You must be an admin of both the source and target organizations to move a project."
                )

        except (OrganizationMembership.DoesNotExist, Organization.DoesNotExist):
            raise exceptions.ValidationError(
                "You must be an admin or owner of both the source and target organizations to move a project."
            )

        if project.organization_id == target_organization_id:
            raise exceptions.ValidationError("Project is already in the target organization.")

        teams = list(project.teams.all())

        with transaction.atomic():
            project.organization_id = target_organization_id
            project.save()

            log_activity(
                organization_id=cast(UUIDT, target_organization_id),
                team_id=project.pk,
                user=user,
                was_impersonated=is_impersonated(request),
                scope="Project",
                item_id=project.pk,
                activity="updated",
                detail=Detail(
                    name="moved to another organization",
                    changes=[
                        Change(
                            type="Project",
                            action="changed",
                            field="organization_id",
                            before=str(current_organization.id),
                            after=str(target_organization.id),
                        )
                    ],
                ),
            )

            for team in teams:
                team.organization_id = target_organization_id
                team.save()

        report_user_action(
            user,
            "project moved to another organization",
            {
                "project_id": project.id,
                "project_name": project.name,
                "old_organization_id": current_organization.id,
                "old_organization_name": current_organization.name,
                "new_organization_id": target_organization_id,
                "new_organization_name": target_organization.name,
            },
            team=teams[0],
            request=request,
        )

        return response.Response(
            ProjectBackwardCompatSerializer(project, context=self.get_serializer_context()).data, status=200
        )

    @cached_property
    def user_permissions(self):
        project = self.get_object() if self.action in actions_that_require_current_team else None
        team = project.passthrough_team if project else None
        return UserPermissions(cast(User, self.request.user), team)


class RootProjectViewSet(ProjectViewSet):
    # NOTE: We don't want people creating projects via the "current_organization" concept, but rather specify the org ID
    # in the URL - hence this is hidden from the API docs, but used in the app
    hide_api_docs = True


class PremiumMultiProjectPermission(BasePermission):
    """Require user to have all necessary premium features on their plan for create access to the endpoint."""

    message = "You have reached the maximum limit of allowed projects for your current plan. Upgrade your plan to be able to create and manage more projects."

    def has_permission(self, request: request.Request, view) -> bool:
        if view.action not in CREATE_ACTIONS:
            return True

        try:
            organization = get_organization_from_view(view)
        except ValueError:
            return False

        if request.data.get("is_demo"):
            # If we're requesting to make a demo project but the org already has a demo project
            if organization.teams.filter(is_demo=True).exists():
                return False

        current_non_demo_project_count = organization.teams.exclude(is_demo=True).distinct("project_id").count()
        projects_feature = organization.get_available_feature(AvailableFeature.ORGANIZATIONS_PROJECTS)

        if projects_feature:
            allowed_project_count = projects_feature.get("limit")
            # If allowed_project_count is None then the user is allowed unlimited projects
            if allowed_project_count is None:
                # We have a hard limit of MAX_ALLOWED_PROJECTS_PER_ORG projects per organization
                # We don't want to block updates if a customer is already over the max allowed
                if current_non_demo_project_count >= MAX_ALLOWED_PROJECTS_PER_ORG and view.action == "create":
                    self.message = f"You have reached the maximum limit of {MAX_ALLOWED_PROJECTS_PER_ORG} projects per organization. Contact support if you'd like access to more projects."
                    return False
                return True
            # Check current limit against allowed limit
            if current_non_demo_project_count >= allowed_project_count:
                return False
        else:
            # If the org doesn't have the feature, they can only have one non-demo project
            if current_non_demo_project_count >= 1:
                return False

        # in any other case, we're good to go
        return True
