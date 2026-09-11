"""Viewsets and endpoint serializers for project settings."""

from functools import cached_property
from typing import Any, cast

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, request, response, serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import TeamBasicSerializer
from posthog.api.utils import action
from posthog.auth import SessionAuthentication
from posthog.decorators import disallow_if_impersonated
from posthog.event_usage import report_user_action
from posthog.helpers.impersonation import is_impersonated
from posthog.models import ProductIntent, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog, Detail, load_activity, log_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.event_ingestion_restriction_config import (
    EventIngestionRestrictionConfig,
    IngestionPipeline,
    RestrictionType,
)
from posthog.models.product_intent.product_intent import ProductIntentSerializer
from posthog.models.team.util import actions_that_require_current_team
from posthog.models.utils import UUIDT
from posthog.permissions import (
    AccessControlPermission,
    APIScopePermission,
    OrganizationMemberPermissions,
    TeamMemberLightManagementPermission,
    TeamMemberStrictManagementPermission,
    UserCanCreateProjectPermission,
    get_authenticator_scoped_organization_ids,
    get_authenticator_scoped_team_ids,
)
from posthog.scopes import APIScopeObjectOrNotSupported
from posthog.user_permissions import UserPermissions
from posthog.utils import get_instance_realm

from products.access_control.backend.presentation.access_control import AccessControlViewSetMixin
from products.access_control.backend.presentation.access_control_settings import AccessControlSettingsViewSetMixin

from . import integration_config, team_config, team_permissions, team_serializer


class EventIngestionRestrictionSerializer(serializers.Serializer):
    restriction_type = serializers.ChoiceField(
        choices=RestrictionType.choices,
        help_text="What happens to matching events: dropped, sent to the overflow lane, or ingested without person processing.",
    )
    distinct_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text="Distinct IDs the restriction applies to. Empty means it is not filtered by distinct ID.",
    )
    session_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text="Session IDs the restriction applies to. Empty means it is not filtered by session ID.",
    )
    event_names = serializers.ListField(
        child=serializers.CharField(),
        help_text="Event names the restriction applies to. Empty means it is not filtered by event name.",
    )
    event_uuids = serializers.ListField(
        child=serializers.CharField(),
        help_text="Event UUIDs the restriction applies to. Empty means it is not filtered by event UUID.",
    )
    pipelines = serializers.ListField(
        child=serializers.ChoiceField(choices=IngestionPipeline.choices),
        help_text="Ingestion pipelines the restriction applies to. Filters combine with AND; values within a filter combine with OR.",
    )


def team_event_ingestion_restrictions_view(team: Team, request: request.Request) -> response.Response:
    restrictions = EventIngestionRestrictionConfig.objects.filter(token=team.api_token)
    data = [
        {
            "restriction_type": restriction.restriction_type,
            "distinct_ids": restriction.distinct_ids or [],
            "session_ids": restriction.session_ids or [],
            "event_names": restriction.event_names or [],
            "event_uuids": restriction.event_uuids or [],
            "pipelines": restriction.pipelines or [],
        }
        for restriction in restrictions
    ]
    return response.Response(EventIngestionRestrictionSerializer(data, many=True).data)


class TeamViewSet(
    TeamAndOrgViewSetMixin, AccessControlSettingsViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet
):
    """
    Projects for the current organization.
    """

    scope_object: APIScopeObjectOrNotSupported = "project"
    serializer_class = team_serializer.TeamSerializer
    queryset = Team.objects.all().select_related("organization")
    lookup_field = "id"
    ordering = "-created_by"

    # Actions whose GET is downgraded to project:read for session auth; mutating methods stay on project:write/admin.
    GET_DOWNGRADE_ACTIONS = ("evaluation_context_suggestions",)

    def safely_get_queryset(self, queryset):
        user = cast(User, self.request.user)
        # IMPORTANT: This is actually what ensures that a user cannot read/update a project for which they don't have permission
        visible_teams_ids = UserPermissions(user).team_ids_visible_for_user
        queryset = queryset.filter(id__in=visible_teams_ids)
        authenticator = self.request.successful_authenticator
        if scoped_organizations := get_authenticator_scoped_organization_ids(authenticator):
            queryset = queryset.filter(project__organization_id__in=scoped_organizations)
        if scoped_teams := get_authenticator_scoped_team_ids(authenticator):
            queryset = queryset.filter(id__in=scoped_teams)
        return queryset

    def get_serializer_class(self) -> type[serializers.BaseSerializer]:
        if self.action == "list":
            return TeamBasicSerializer
        return super().get_serializer_class()

    def dangerously_get_required_scopes(self, request, view) -> list[str] | None:
        # Used for the AccessControlViewSetMixin
        mixin_result = super().dangerously_get_required_scopes(request, view)
        if mixin_result is not None:
            return mixin_result

        # NOTE: This downgrade only applies to session-based auth (browser users).
        # All other auth methods (API keys, OAuth tokens, etc.) must have project:write
        # to modify any fields, preserving the semantic meaning of read-only API keys.
        if self.action == "partial_update":
            is_session_auth = isinstance(request.successful_authenticator, SessionAuthentication)
            if is_session_auth:
                request_fields = set(request.data.keys())
                # Member-safe fields, plus fields whose write is governed by their own field-level
                # access control — keep the request gate from demanding project:write (admin) for the
                # latter, otherwise e.g. a web analytics editor on a restricted project is blocked
                # before UserAccessControlSerializerMixin.validate can authorize the field.
                downgradable_fields = (
                    team_config.TEAM_CONFIG_MEMBER_FIELDS_SET | team_config.TEAM_CONFIG_FIELD_ACCESS_CONTROLLED_FIELDS
                )
                if request_fields and request_fields.issubset(downgradable_fields):
                    return ["project:read"]

        # Read-only access for member-readable actions — only downgrade GET, not writes.
        if self.action in self.GET_DOWNGRADE_ACTIONS and request.method == "GET":
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
            AccessControlPermission,
            team_permissions.PremiumMultiEnvironmentPermission,
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
                # Skip TeamMemberAccessPermission for list action, as list is serialized with limited TeamBasicSerializer.
                # GET_DOWNGRADE_ACTIONS writes stay admin-gated via TeamMemberStrictManagementPermission.
                if self.action in self.GET_DOWNGRADE_ACTIONS:
                    if self.request.method != "GET":
                        # Writes need strict (admin for all non-safe methods), not light (which only gates DELETE).
                        permissions.append(TeamMemberStrictManagementPermission)
                else:
                    permissions.append(TeamMemberLightManagementPermission)

        return [permission() for permission in permissions]

    def safely_get_object(self, queryset):
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@current":
            team = getattr(self.request.user, "team", None)
            if team is None:
                raise exceptions.NotFound()
            # This branch answers from the user's own state instead of the scoped queryset. A project
            # that moved between organizations leaves that state naming an environment the token's
            # organizations no longer cover, so apply the same restriction the queryset would have.
            scoped_organizations = get_authenticator_scoped_organization_ids(self.request.successful_authenticator)
            if scoped_organizations and str(team.organization_id) not in scoped_organizations:
                raise exceptions.NotFound()
            return team

        filter_kwargs = {self.lookup_field: lookup_value}
        try:
            team = get_object_or_404(queryset, **filter_kwargs)
        except ValueError as error:
            raise exceptions.ValidationError(str(error))
        return team

    # :KLUDGE: Exposed for compatibility reasons for permission classes.
    @property
    def team(self):
        return self.get_object()

    def perform_destroy(self, team: Team):
        # Check if bulk deletion operations are disabled via environment variable
        if settings.DISABLE_BULK_DELETES:
            raise exceptions.ValidationError(
                "Team deletion is temporarily disabled during database migration. Please try again later."
            )

        team_id = team.pk
        organization_id = team.organization_id
        team_name = team.name

        # Remove the team from the org's managed warehouse first (no-op for orgs without
        # one). Blocks when duckgres refuses — e.g. the warehouse's last team, which
        # requires deprovisioning the warehouse (or deleting the organization) instead.
        # Keep the product API off the core import path.
        from products.managed_warehouse.backend.facade.api import get_team_deletion_block_reason  # noqa: PLC0415

        warehouse_block_reason = get_team_deletion_block_reason(team_id, organization_id)
        if warehouse_block_reason:
            raise exceptions.ValidationError(warehouse_block_reason)

        user = cast(User, self.request.user)

        # Hand off all deletion work (bulky postgres, batch exports, team record,
        # ClickHouse, email) to the durable Temporal workflow.
        from posthog.temporal.delete_teams.dispatch import start_delete_project_data_workflow

        start_delete_project_data_workflow(
            team_ids=[team_id],
            project_id=None,  # Only deleting a team, not the whole project
            user_id=user.id,
            project_name=team_name,
        )

        log_activity(
            organization_id=cast(UUIDT, organization_id),
            team_id=team_id,
            user=user,
            was_impersonated=is_impersonated(self.request),
            scope="Team",
            item_id=team_id,
            activity="deleted",
            detail=Detail(name=str(team_name)),
        )
        # TRICKY: We pass in `team` here as access to `user.current_team` can fail if it was deleted
        report_user_action(user, "team deleted", team=team, request=self.request)

    @action(
        methods=["PATCH"],
        detail=True,
        # Only ADMIN or higher users are allowed to access this project
        permission_classes=[TeamMemberStrictManagementPermission],
    )
    def reset_token(self, request: request.Request, id: str, **kwargs) -> response.Response:
        team = self.get_object()
        team.reset_token_and_save(user=request.user, is_impersonated_session=is_impersonated(request))
        return response.Response(team_serializer.TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(
        methods=["PATCH"],
        detail=True,
        # Only ADMIN or higher users are allowed to access this project
        permission_classes=[TeamMemberStrictManagementPermission],
    )
    def rotate_secret_token(self, request: request.Request, id: str, **kwargs) -> response.Response:
        team = self.get_object()
        integration_config.validate_secret_token_generation(team, cast(User, request.user))
        team.rotate_secret_token_and_save(user=request.user, is_impersonated_session=is_impersonated(request))
        return response.Response(team_serializer.TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(
        methods=["PATCH"],
        detail=True,
        # Only ADMIN or higher users are allowed to access this project
        permission_classes=[TeamMemberStrictManagementPermission],
    )
    def delete_secret_token_backup(self, request: request.Request, id: str, **kwargs) -> response.Response:
        team = self.get_object()
        team.delete_secret_token_backup_and_save(user=request.user, is_impersonated_session=is_impersonated(request))
        return response.Response(team_serializer.TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(
        methods=["POST"],
        detail=True,
        # Only ADMIN or higher users are allowed to access this project
        permission_classes=[TeamMemberStrictManagementPermission],
    )
    def generate_conversations_public_token(self, request: request.Request, id: str, **kwargs) -> response.Response:
        team = self.get_object()
        team.generate_conversations_public_token_and_save(
            user=request.user, is_impersonated_session=is_impersonated(request)
        )
        return response.Response(team_serializer.TeamSerializer(team, context=self.get_serializer_context()).data)

    @action(
        methods=["GET", "PATCH"],
        detail=True,
        permission_classes=[TeamMemberStrictManagementPermission],
        url_path="logs_config",
    )
    def logs_config(self, request: request.Request, id: str, **kwargs) -> response.Response:
        """Manage logs product configuration for this environment. Members can read;
        writing requires project admin, matching the admin-only settings UI."""
        return integration_config.handle_logs_config(request, self.get_object())

    @extend_schema(
        methods=["GET"],
        request=None,
        responses={200: integration_config.TeamTracingConfigSerializer},
        extensions={"x-product": "tracing"},
    )
    @extend_schema(
        methods=["PATCH"],
        request=integration_config.TeamTracingConfigSerializer,
        responses={200: integration_config.TeamTracingConfigSerializer},
        extensions={"x-product": "tracing"},
    )
    @action(
        methods=["GET", "PATCH"],
        detail=True,
        permission_classes=[TeamMemberStrictManagementPermission],
        url_path="tracing_config",
    )
    def tracing_config(self, request: request.Request, id: str, **kwargs) -> response.Response:
        """Manage tracing product configuration for this environment. Members can read;
        writing requires project admin, matching the admin-only settings UI."""
        return integration_config.handle_tracing_config(request, self.get_object())

    @action(
        methods=["GET", "PATCH"],
        detail=True,
        permission_classes=[TeamMemberStrictManagementPermission],
        url_path="experiments_config",
    )
    def experiments_config(self, request: request.Request, id: str, **kwargs) -> response.Response:
        """Manage experiment configuration for this environment."""
        return integration_config.handle_experiments_config(request, self.get_object())

    @extend_schema(
        methods=["POST"],
        request=team_serializer.EvaluationContextSuggestionRequestSerializer,
        responses={200: team_serializer.EvaluationContextSuggestionResponseSerializer},
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
        responses={200: team_serializer.EvaluationContextSuggestionResponseSerializer},
        extensions={"x-product": "feature_flags"},
    )
    @action(
        methods=["POST", "DELETE"],
        detail=True,
        permission_classes=[IsAuthenticated],
    )
    def evaluation_context_suggestions(self, request: request.Request, id: str, **kwargs) -> response.Response:
        """Hide an evaluation context name from the flag editor's suggestion list, or restore it.

        POST hides the name; DELETE restores it. The underlying context row and any flags already
        using it are never modified — this only controls what gets suggested.
        """
        return integration_config.handle_evaluation_context_suggestions(request, self.get_object())

    @action(
        methods=["GET"],
        detail=True,
        permission_classes=[IsAuthenticated],
    )
    def is_generating_demo_data(self, request: request.Request, id: str, **kwargs) -> response.Response:
        team = self.get_object()
        return response.Response({"is_generating_demo_data": team.get_is_generating_demo_data()})

    @action(methods=["GET"], detail=True)
    def activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        team = self.get_object()

        activity_page = load_activity(
            scope="Team",
            team_id=team.pk,
            item_ids=[str(team.pk)],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["GET"], detail=True)
    def settings_as_of(self, request: request.Request, **kwargs) -> response.Response:
        """
        Return the team settings as of the provided timestamp.
        Query params:
        - at: ISO8601 datetime (required)
        - scope: optional, one or multiple keys to filter the returned settings
        """
        team = self.get_object()

        at_param = request.query_params.get("at")
        if not at_param:
            raise exceptions.ValidationError({"at": "Query parameter 'at' is required (ISO8601)."})

        as_of = parse_datetime(at_param)
        if as_of is None:
            raise exceptions.ValidationError(
                {"at": "Invalid datetime format. Use ISO8601 (e.g., 2025-11-24T12:34:56Z)."}
            )
        if timezone.is_naive(as_of):
            as_of = timezone.make_aware(as_of)

        # Build starting snapshot from current model values for config fields
        settings_fields = set(team_config.TEAM_CONFIG_FIELDS)
        snapshot: dict[str, Any] = {}
        for field_name in settings_fields:
            if hasattr(team, field_name):
                snapshot[field_name] = getattr(team, field_name)
            elif hasattr(team, f"{field_name}_id"):
                snapshot[field_name] = getattr(team, f"{field_name}_id")
            else:
                snapshot[field_name] = None

        # Fetch Team-scoped activity logs after the target timestamp
        logs = (
            ActivityLog.objects.filter(team_id=team.id, scope="Team", item_id=str(team.id), created_at__gt=as_of)
            .order_by("-created_at")
            .only("detail", "created_at", "activity")
        )

        # Roll back newest → oldest
        for log in logs.iterator():
            detail = log.detail or {}
            changes = detail.get("changes") or []
            for change in changes:
                field = change.get("field")
                action = change.get("action")
                before = change.get("before")

                # Normalize FK fields (e.g., primary_dashboard_id → primary_dashboard)
                target = field[:-3] if isinstance(field, str) and field.endswith("_id") else field
                if target not in settings_fields:
                    continue

                if action == "changed":
                    snapshot[target] = before
                elif action == "created":
                    snapshot[target] = None
                elif action == "deleted":
                    snapshot[target] = before
                # Other actions (created/deleted without relevant field) are ignored

        # Optional scope filtering
        scope_values = request.query_params.getlist("scope")

        if scope_values:
            filtered = {k: snapshot.get(k, None) for k in scope_values}
            return response.Response(filtered)

        return response.Response(snapshot)

    @action(
        methods=["PATCH"],
        detail=True,
        required_scopes=["project:read"],
    )
    @disallow_if_impersonated(message="Impersonated sessions cannot set product intents.")
    def add_product_intent(self, request: request.Request, *args, **kwargs):
        team = self.get_object()
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

        return response.Response(
            team_serializer.TeamSerializer(team, context=self.get_serializer_context()).data, status=201
        )

    @action(
        methods=["PATCH"],
        detail=True,
        required_scopes=["project:read"],
    )
    @disallow_if_impersonated(message="Impersonated sessions cannot set product intents.")
    def complete_product_onboarding(self, request: request.Request, *args, **kwargs):
        team = self.get_object()
        product_type = request.data.get("product_type")
        user = request.user
        current_url = request.headers.get("Referer")
        session_id = request.headers.get("X-Posthog-Session-Id")

        if not product_type:
            return response.Response({"error": "product_type is required"}, status=400)

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

        return response.Response(team_serializer.TeamSerializer(team, context=self.get_serializer_context()).data)

    @extend_schema(responses=EventIngestionRestrictionSerializer(many=True))
    @action(
        methods=["GET"],
        detail=True,
        required_scopes=["project:read"],
        url_path="event_ingestion_restrictions",
        pagination_class=None,
    )
    def event_ingestion_restrictions(self, request, **kwargs):
        return team_event_ingestion_restrictions_view(self.get_object(), request)

    @cached_property
    def user_permissions(self):
        team = self.get_object() if self.action in actions_that_require_current_team else None
        return UserPermissions(cast(User, self.request.user), team)


class RootTeamViewSet(TeamViewSet):
    # NOTE: We don't want people creating environments via the "current_organization"/"current_project" concept, but
    # rather specify the org ID and project ID in the URL - hence this is hidden from the API docs, but used in the app
    hide_api_docs = True


class ProjectEnvironmentsViewSet(TeamViewSet):
    """Deprecated: use /api/environments/{id}/ instead.

    Hidden from the API docs, so the actions it inherits from TeamViewSet do not reach the
    generated types and MCP tools under a route that rejects every request."""

    hide_api_docs = True

    def initial(self, request: request.Request, *args, **kwargs) -> None:
        raise exceptions.PermissionDenied(
            "Multiple environments per project are no longer available. Please contact support if you need assistance."
        )
