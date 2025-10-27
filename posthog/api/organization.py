import json
import dataclasses
from functools import cached_property
from typing import Any, Optional, Union, cast

from django.db.models import Model, QuerySet
from django.dispatch import receiver
from django.shortcuts import get_object_or_404

import posthoganalytics
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog import settings
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import ProjectBasicSerializer, TeamBasicSerializer
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.cloud_utils import is_cloud
from posthog.constants import INTERNAL_BOT_EMAIL_SUFFIX, AvailableFeature
from posthog.event_usage import groups, report_organization_action, report_organization_deleted
from posthog.exceptions_capture import capture_exception
from posthog.models import Organization, Team, User
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, changes_between, log_activity
from posthog.models.activity_logging.model_activity import ImpersonatedContext
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_invite import OrganizationInvite
from posthog.models.signals import model_activity_signal, mute_selected_signals
from posthog.models.team.util import delete_bulky_postgres_data
from posthog.models.uploaded_media import UploadedMedia
from posthog.permissions import (
    CREATE_ACTIONS,
    APIScopePermission,
    OrganizationAdminWritePermissions,
    OrganizationMemberPermissions,
    TimeSensitiveActionPermission,
    extract_organization,
)
from posthog.rbac.migrations.rbac_feature_flag_migration import rbac_feature_flag_role_access_migration
from posthog.rbac.migrations.rbac_team_migration import rbac_team_access_control_migration
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin
from posthog.user_permissions import UserPermissions, UserPermissionsSerializerMixin


class PremiumMultiorganizationPermission(permissions.BasePermission):
    """Require user to have all necessary premium features on their plan for create access to the endpoint."""

    message = "You must upgrade your PostHog plan to be able to create and manage multiple organizations."

    def has_permission(self, request: Request, view) -> bool:
        user = cast(User, request.user)
        if (
            view.action in CREATE_ACTIONS
            and (
                user.organization is None
                or not user.organization.is_feature_available(AvailableFeature.ORGANIZATIONS_PROJECTS)
            )
            and user.organizations.count() >= 1
        ):
            return False
        return True


class OrganizationPermissionsWithDelete(OrganizationAdminWritePermissions):
    def has_object_permission(self, request: Request, view, object: Model) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        # TODO: Optimize so that this computation is only done once, on `OrganizationMemberPermissions`
        organization = extract_organization(object, view)
        min_level = (
            OrganizationMembership.Level.OWNER if request.method == "DELETE" else OrganizationMembership.Level.ADMIN
        )
        return (
            OrganizationMembership.objects.get(user=cast(User, request.user), organization=organization).level
            >= min_level
        )


class OrganizationPermissionsWithEnvRollback(OrganizationAdminWritePermissions):
    def has_object_permission(self, request: Request, view, object: Model) -> bool:
        organization = extract_organization(object, view)

        return (
            OrganizationMembership.objects.get(user=cast(User, request.user), organization=organization).level
            >= OrganizationMembership.Level.ADMIN
        )


class OrganizationSerializer(
    serializers.ModelSerializer, UserPermissionsSerializerMixin, UserAccessControlSerializerMixin
):
    membership_level = serializers.SerializerMethodField()
    teams = serializers.SerializerMethodField()
    projects = serializers.SerializerMethodField()
    metadata = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()
    logo_media_id = serializers.PrimaryKeyRelatedField(
        queryset=UploadedMedia.objects.all(), required=False, allow_null=True
    )
    default_role_id = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="ID of the role to automatically assign to new members joining the organization",
    )

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
            "slug",
            "logo_media_id",
            "created_at",
            "updated_at",
            "membership_level",
            "plugins_access_level",
            "teams",
            "projects",
            "available_product_features",
            "is_member_join_email_enabled",
            "metadata",
            "customer_id",
            "enforce_2fa",
            "members_can_invite",
            "members_can_use_personal_api_keys",
            "allow_publicly_shared_resources",
            "member_count",
            "is_ai_data_processing_approved",
            "default_experiment_stats_method",
            "default_role_id",
        ]
        read_only_fields = [
            "id",
            "slug",
            "created_at",
            "updated_at",
            "membership_level",
            "plugins_access_level",
            "teams",
            "projects",
            "available_product_features",
            "metadata",
            "customer_id",
            "member_count",
            "default_role_id",
        ]
        extra_kwargs = {
            "slug": {
                "required": False,
            },  # slug is not required here as it's generated automatically for new organizations
        }

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Organization:
        serializers.raise_errors_on_nested_writes("create", self, validated_data)
        user = self.context["request"].user
        organization, _, _ = Organization.objects.bootstrap(user, **validated_data)
        return organization

    def get_membership_level(self, organization: Organization) -> Optional[OrganizationMembership.Level]:
        membership = self.user_permissions.organization_memberships.get(organization.pk)
        return membership.level if membership is not None else None

    def get_teams(self, instance: Organization) -> list[dict[str, Any]]:
        # Support new access control system
        visible_teams = (
            self.user_access_control.filter_queryset_by_access_level(instance.teams.all(), include_all_if_admin=True)
            if self.user_access_control
            else instance.teams.none()
        )
        # Support old access control system
        visible_teams = visible_teams.filter(id__in=self.user_permissions.team_ids_visible_for_user).select_related(
            "project"
        )
        return TeamBasicSerializer(visible_teams, context=self.context, many=True).data  # type: ignore

    def get_projects(self, instance: Organization) -> list[dict[str, Any]]:
        visible_projects = instance.projects.filter(id__in=self.user_permissions.project_ids_visible_for_user)
        return ProjectBasicSerializer(visible_projects, context=self.context, many=True).data  # type: ignore

    def get_metadata(self, instance: Organization) -> dict[str, Union[str, int, object]]:
        return {
            "instance_tag": settings.INSTANCE_TAG,
        }

    def get_member_count(self, organization: Organization):
        return (
            OrganizationMembership.objects.exclude(user__email__endswith=INTERNAL_BOT_EMAIL_SUFFIX)
            .filter(
                user__is_active=True,
            )
            .filter(organization=organization)
            .count()
        )


class OrganizationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "organization"
    serializer_class = OrganizationSerializer
    permission_classes = [OrganizationPermissionsWithDelete, TimeSensitiveActionPermission]
    queryset = Organization.objects.none()
    lookup_field = "id"
    ordering = "-created_by"

    def dangerously_get_permissions(self):
        if self.action == "list":
            return [permission() for permission in [permissions.IsAuthenticated, APIScopePermission]]

        if self.action == "create":
            # Cannot use `OrganizationMemberPermissions` or `OrganizationAdminWritePermissions`
            # because they require an existing org, unneeded anyways because permissions are organization-based
            create_permissions = [
                permission()
                for permission in [permissions.IsAuthenticated, TimeSensitiveActionPermission, APIScopePermission]
            ]
            if not is_cloud():
                create_permissions.append(PremiumMultiorganizationPermission())

            return create_permissions

        if self.action in ["update", "partial_update"]:
            update_permissions = [
                permission()
                for permission in [
                    permissions.IsAuthenticated,
                    TimeSensitiveActionPermission,
                    APIScopePermission,
                    OrganizationAdminWritePermissions,
                ]
            ]

            if not is_cloud():
                update_permissions.append(PremiumMultiorganizationPermission())

            return update_permissions

        # We don't override for other actions
        raise NotImplementedError()

    def safely_get_queryset(self, queryset) -> QuerySet:
        user = cast(User, self.request.user)
        queryset = user.organizations.all()
        if isinstance(self.request.successful_authenticator, PersonalAPIKeyAuthentication):
            if scoped_organizations := self.request.successful_authenticator.personal_api_key.scoped_organizations:
                queryset = queryset.filter(id__in=scoped_organizations)
        if isinstance(self.request.successful_authenticator, OAuthAccessTokenAuthentication):
            if scoped_organizations := self.request.successful_authenticator.access_token.scoped_organizations:
                queryset = queryset.filter(id__in=scoped_organizations)

        return queryset

    def safely_get_object(self, queryset):
        return self.organization

    # Override base view as the "parent_query_dict" for an organization is the same as the organization itself
    @cached_property
    def organization(self) -> Organization:
        if not self.detail:
            raise AttributeError("Not valid for non-detail routes.")
        queryset = self.filter_queryset(self.get_queryset())
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@current":
            organization = cast(User, self.request.user).organization
            if organization is None:
                raise exceptions.NotFound("Current organization not found.")
            return organization

        filter_kwargs = {self.lookup_field: lookup_value}
        return get_object_or_404(queryset, **filter_kwargs)

    def perform_destroy(self, organization: Organization):
        # Check if bulk deletion operations are disabled via environment variable
        # Organizations contain teams, so we need to block organization deletion too
        if settings.DISABLE_BULK_DELETES:
            raise exceptions.ValidationError(
                "Organization deletion is temporarily disabled during database migration. Please try again later."
            )

        user = cast(User, self.request.user)
        report_organization_deleted(user, organization)
        team_ids = [team.pk for team in organization.teams.all()]
        delete_bulky_postgres_data(team_ids=team_ids)
        with mute_selected_signals():
            super().perform_destroy(organization)
        # Once the organization is deleted, queue deletion of associated data
        AsyncDeletion.objects.bulk_create(
            [
                AsyncDeletion(
                    deletion_type=DeletionType.Team,
                    team_id=team_id,
                    key=str(team_id),
                    created_by=user,
                )
                for team_id in team_ids
            ],
            ignore_conflicts=True,
        )

    def get_serializer_context(self) -> dict[str, Any]:
        return {
            **super().get_serializer_context(),
            "user_permissions": UserPermissions(cast(User, self.request.user)),
        }

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if "enforce_2fa" in request.data:
            enforce_2fa_value = request.data["enforce_2fa"]
            organization = self.get_object()
            user = cast(User, request.user)

            # Add capture event for 2FA enforcement change
            posthoganalytics.capture(
                "organization 2fa enforcement toggled",
                distinct_id=str(user.distinct_id),
                properties={
                    "enabled": enforce_2fa_value,
                    "organization_id": str(organization.id),
                    "organization_name": organization.name,
                    "user_role": user.organization_memberships.get(organization=organization).level,
                },
                groups=groups(organization),
            )

        # Set user context for activity logging
        with ImpersonatedContext(request):
            return super().update(request, *args, **kwargs)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if "enforce_2fa" in request.data:
            enforce_2fa_value = request.data["enforce_2fa"]
            organization = self.get_object()
            user = cast(User, request.user)

            # Add capture event for 2FA enforcement change
            posthoganalytics.capture(
                "organization 2fa enforcement toggled",
                distinct_id=str(user.distinct_id),
                properties={
                    "enabled": enforce_2fa_value,
                    "organization_id": str(organization.id),
                    "organization_name": organization.name,
                    "user_role": user.organization_memberships.get(organization=organization).level,
                },
                groups=groups(organization),
            )

        # Set user context for activity logging
        with ImpersonatedContext(request):
            return super().partial_update(request, *args, **kwargs)

    def perform_create(self, serializer):
        # Set user context for activity logging
        with ImpersonatedContext(self.request):
            super().perform_create(serializer)

    @extend_schema(exclude=True)
    @action(detail=True, methods=["post"])
    def migrate_access_control(self, request: Request, **kwargs) -> Response:
        organization = Organization.objects.get(id=kwargs["id"])
        self.check_object_permissions(request, organization)

        try:
            user = cast(User, request.user)
            report_organization_action(organization, "rbac_team_migration_started", {"user": user.distinct_id})

            rbac_team_access_control_migration(organization.id)
            rbac_feature_flag_role_access_migration(organization.id)

            report_organization_action(organization, "rbac_team_migration_completed", {"user": user.distinct_id})

        except Exception as e:
            report_organization_action(
                organization, "rbac_team_migration_failed", {"user": user.distinct_id, "error": str(e)}
            )
            capture_exception(e)
            return Response({"status": False, "error": "An internal error has occurred."}, status=500)

        return Response({"status": True})

    @action(
        methods=["POST"],
        detail=True,
        url_path="environments_rollback",
        permission_classes=[
            permissions.IsAuthenticated,
            OrganizationMemberPermissions,
            OrganizationPermissionsWithEnvRollback,
        ],
    )
    def environments_rollback(self, request: Request, **kwargs) -> Response:
        """
        Trigger environments rollback migration for users previously on multi-environment projects.
        The request data should be a mapping of source environment IDs to target environment IDs.
        Example: { "2": 2, "116911": 2, "99346": 99346, "140256": 99346 }
        """
        from posthog.storage.environments_rollback_storage import (
            add_organization_to_rollback_list,
            is_organization_rollback_triggered,
        )
        from posthog.tasks.tasks import environments_rollback_migration

        organization = self.get_object()

        if is_organization_rollback_triggered(organization.id):
            raise exceptions.ValidationError("Environments rollback has already been requested for this organization.")

        environment_mappings: dict[str, int] = {str(k): int(v) for k, v in request.data.items()}
        user = cast(User, request.user)
        membership = user.organization_memberships.get(organization=organization)

        if not environment_mappings:
            raise exceptions.ValidationError("Environment mappings are required")

        # Verify all environments exist and belong to this organization
        all_environment_ids = set(map(int, environment_mappings.keys())) | set(environment_mappings.values())
        teams = Team.objects.filter(id__in=all_environment_ids, organization_id=organization.id)
        found_team_ids = set(teams.values_list("id", flat=True))

        missing_team_ids = all_environment_ids - found_team_ids
        if missing_team_ids:
            raise exceptions.ValidationError(f"Environments not found: {missing_team_ids}")

        # Trigger the async task to perform the migration
        environments_rollback_migration.delay(
            organization_id=organization.id,
            environment_mappings=environment_mappings,
            user_id=user.id,
        )

        # Mark organization as having triggered rollback in Redis
        add_organization_to_rollback_list(organization.id)

        posthoganalytics.capture(
            "organization environments rollback started",
            distinct_id=str(user.distinct_id),
            properties={
                "environment_mappings": json.dumps(environment_mappings),
                "organization_id": str(organization.id),
                "organization_name": organization.name,
                "user_role": membership.level,
            },
            groups=groups(organization),
        )

        return Response({"success": True, "message": "Migration started"}, status=202)


@receiver(model_activity_signal, sender=Organization)
def handle_organization_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    log_activity(
        organization_id=after_update.id,
        team_id=None,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=after_update.name,
        ),
    )


@dataclasses.dataclass(frozen=True)
class OrganizationMembershipContext(ActivityContextBase):
    organization_id: str
    organization_name: str
    user_id: str
    user_email: str
    user_name: str
    level: str


@dataclasses.dataclass(frozen=True)
class OrganizationInviteContext(ActivityContextBase):
    organization_id: str
    organization_name: str
    target_email: str
    inviter_user_id: Optional[str]
    inviter_user_email: Optional[str]
    inviter_user_name: Optional[str]
    level: str


@receiver(model_activity_signal, sender=OrganizationMembership)
def handle_organization_membership_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    # Use after_update for create/update, before_update for delete
    membership = after_update or before_update

    if not membership:
        return

    member_user = membership.user
    member_name = f"{member_user.first_name} {member_user.last_name}".strip()

    context = OrganizationMembershipContext(
        organization_id=str(membership.organization_id),
        organization_name=membership.organization.name,
        user_id=str(member_user.id),
        user_email=member_user.email,
        user_name=member_name,
        level=str(OrganizationMembership.Level(membership.level).label),
    )

    if activity == "created":
        detail_name = f"{member_name} ({member_user.email}) joined {membership.organization.name}"
    elif activity == "deleted":
        detail_name = f"{member_name} ({member_user.email}) left {membership.organization.name}"
    else:
        detail_name = f"{member_name} ({member_user.email}) membership updated in {membership.organization.name}"

    log_activity(
        organization_id=membership.organization_id,
        team_id=None,
        user=user,
        was_impersonated=was_impersonated,
        item_id=membership.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=detail_name,
            context=context,
        ),
    )


@receiver(model_activity_signal, sender=OrganizationInvite)
def handle_organization_invite_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    # Use after_update for create/update, before_update for delete
    invite = after_update or before_update

    if not invite:
        return

    inviter_user = invite.created_by
    inviter_name = f"{inviter_user.first_name} {inviter_user.last_name}".strip() if inviter_user else None

    context = OrganizationInviteContext(
        organization_id=str(invite.organization_id),
        organization_name=invite.organization.name,
        target_email=invite.target_email,
        inviter_user_id=str(inviter_user.id) if inviter_user else None,
        inviter_user_email=inviter_user.email if inviter_user else None,
        inviter_user_name=inviter_name,
        level=str(OrganizationMembership.Level(invite.level).label),
    )

    if activity == "created":
        if inviter_user:
            detail_name = f"User {inviter_name} ({inviter_user.email}) invited user {invite.target_email} into organization {invite.organization.name}"
        else:
            detail_name = f"User {invite.target_email} was invited to organization {invite.organization.name}"
    elif activity == "deleted":
        detail_name = f"Invite for {invite.target_email} to organization {invite.organization.name} was cancelled"
    else:
        detail_name = f"Invite for {invite.target_email} to organization {invite.organization.name} was updated"

    log_activity(
        organization_id=invite.organization_id,
        team_id=None,
        user=user,
        was_impersonated=was_impersonated,
        item_id=invite.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=detail_name,
            context=context,
        ),
    )
