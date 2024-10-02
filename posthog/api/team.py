import json
from functools import cached_property
from typing import Any, Optional, cast
from datetime import timedelta
from uuid import UUID

from django.shortcuts import get_object_or_404
from loginas.utils import is_impersonated_session
from posthog.jwt import PosthogJwtAudience, encode_jwt
from rest_framework.permissions import BasePermission, IsAuthenticated
from posthog.api.utils import action
from rest_framework import exceptions, request, response, serializers, viewsets

from posthog.geoip import get_geoip_properties
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import TeamBasicSerializer
from posthog.constants import AvailableFeature
from posthog.event_usage import report_user_action
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import (
    Detail,
    dict_changes_between,
    load_activity,
    log_activity,
)
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import APIScopeObjectOrNotSupported
from posthog.models.project import Project
from posthog.models.signals import mute_selected_signals
from posthog.models.team.util import delete_batch_exports, delete_bulky_postgres_data
from posthog.models.utils import UUIDT
from posthog.permissions import (
    CREATE_METHODS,
    APIScopePermission,
    OrganizationAdminWritePermissions,
    OrganizationMemberPermissions,
    TeamMemberLightManagementPermission,
    TeamMemberStrictManagementPermission,
    get_organization_from_view,
)
from posthog.user_permissions import UserPermissions, UserPermissionsSerializerMixin
from posthog.utils import get_ip_address, get_week_start_for_country_code


class PremiumMultiProjectPermissions(BasePermission):  # TODO: Rename to include "Env" in name
    """Require user to have all necessary premium features on their plan for create access to the endpoint."""

    message = "You must upgrade your PostHog plan to be able to create and manage multiple projects or environments."

    def has_permission(self, request: request.Request, view) -> bool:
        if request.method in CREATE_METHODS:
            try:
                organization = get_organization_from_view(view)
            except ValueError:
                return False

            if not request.data.get("is_demo"):
                # if we're not requesting to make a demo project
                # and if the org already has more than 1 non-demo project (need to be able to make the initial project)
                # and the org isn't allowed to make multiple projects
                if organization.teams.exclude(is_demo=True).count() >= 1 and not organization.is_feature_available(
                    AvailableFeature.ORGANIZATIONS_PROJECTS
                ):
                    return False
            else:
                # if we ARE requesting to make a demo project
                # but the org already has a demo project
                if organization.teams.filter(is_demo=True).count() > 0:
                    return False

            # in any other case, we're good to go
            return True
        else:
            return True


class CachingTeamSerializer(serializers.ModelSerializer):
    """
    This serializer is used for caching teams.
    Currently used only in `/decide` endpoint.
    Has all parameters needed for a successful decide request.
    """

    class Meta:
        model = Team
        fields = [
            "id",
            "uuid",
            "name",
            "api_token",
            "autocapture_opt_out",
            "autocapture_exceptions_opt_in",
            "autocapture_web_vitals_opt_in",
            "autocapture_web_vitals_allowed_metrics",
            "autocapture_exceptions_errors_to_ignore",
            "capture_performance_opt_in",
            "capture_console_log_opt_in",
            "session_recording_opt_in",
            "session_recording_sample_rate",
            "session_recording_minimum_duration_milliseconds",
            "session_recording_linked_flag",
            "session_recording_network_payload_capture_config",
            "session_replay_config",
            "recording_domains",
            "inject_web_apps",
            "surveys_opt_in",
            "heatmaps_opt_in",
        ]


class TeamSerializer(serializers.ModelSerializer, UserPermissionsSerializerMixin):
    instance: Optional[Team]

    effective_membership_level = serializers.SerializerMethodField()
    has_group_types = serializers.SerializerMethodField()
    live_events_token = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = (
            "id",
            "uuid",
            "organization",
            "project_id",
            "api_token",
            "app_urls",
            "name",
            "slack_incoming_webhook",
            "created_at",
            "updated_at",
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
            "session_replay_config",
            "effective_membership_level",
            "access_control",
            "week_start_day",
            "has_group_types",
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
            "live_events_token",
        )
        read_only_fields = (
            "id",
            "uuid",
            "organization",
            "project_id",
            "api_token",
            "created_at",
            "updated_at",
            "ingested_event",
            "effective_membership_level",
            "has_group_types",
            "default_modifiers",
            "person_on_events_querying_enabled",
            "live_events_token",
        )

    def get_effective_membership_level(self, team: Team) -> Optional[OrganizationMembership.Level]:
        return self.user_permissions.team(team).effective_membership_level

    def get_has_group_types(self, team: Team) -> bool:
        return GroupTypeMapping.objects.filter(team_id=team.id).exists()

    def get_live_events_token(self, team: Team) -> Optional[str]:
        return encode_jwt(
            {"team_id": team.id, "api_token": team.api_token},
            timedelta(days=7),
            PosthogJwtAudience.LIVESTREAM,
        )

    @staticmethod
    def validate_session_recording_linked_flag(value) -> dict | None:
        if value is None:
            return None

        if not isinstance(value, dict):
            raise exceptions.ValidationError("Must provide a dictionary or None.")
        received_keys = value.keys()
        valid_keys = [
            {"id", "key"},
            {"id", "key", "variant"},
        ]
        if received_keys not in valid_keys:
            raise exceptions.ValidationError(
                "Must provide a dictionary with only 'id' and 'key' keys. _or_ only 'id', 'key', and 'variant' keys."
            )

        return value

    @staticmethod
    def validate_session_recording_network_payload_capture_config(value) -> dict | None:
        if value is None:
            return None

        if not isinstance(value, dict):
            raise exceptions.ValidationError("Must provide a dictionary or None.")

        if not all(key in ["recordHeaders", "recordBody"] for key in value.keys()):
            raise exceptions.ValidationError(
                "Must provide a dictionary with only 'recordHeaders' and/or 'recordBody' keys."
            )

        return value

    @staticmethod
    def validate_session_replay_config(value) -> dict | None:
        if value is None:
            return None

        if not isinstance(value, dict):
            raise exceptions.ValidationError("Must provide a dictionary or None.")

        known_keys = ["record_canvas", "ai_config"]
        if not all(key in known_keys for key in value.keys()):
            raise exceptions.ValidationError(
                f"Must provide a dictionary with only known keys. One or more of {', '.join(known_keys)}."
            )

        if "ai_config" in value:
            TeamSerializer.validate_session_replay_ai_summary_config(value["ai_config"])

        return value

    @staticmethod
    def validate_session_replay_ai_summary_config(value: dict | None) -> dict | None:
        if value is not None:
            if not isinstance(value, dict):
                raise exceptions.ValidationError("Must provide a dictionary or None.")

            allowed_keys = [
                "included_event_properties",
                "opt_in",
                "preferred_events",
                "excluded_events",
                "important_user_properties",
            ]
            if not all(key in allowed_keys for key in value.keys()):
                raise exceptions.ValidationError(
                    f"Must provide a dictionary with only allowed keys: {', '.join(allowed_keys)}."
                )

        return value

    def validate(self, attrs: Any) -> Any:
        attrs = validate_team_attrs(attrs, self.context["view"], self.context["request"], self.instance)
        return super().validate(attrs)

    def create(self, validated_data: dict[str, Any], **kwargs) -> Team:
        request = self.context["request"]
        if "project_id" not in self.context:
            raise exceptions.ValidationError(
                "Environments must be created under a specific project. Send the POST request to /api/projects/<project_id>/environments/ instead."
            )
        if self.context["project_id"] not in self.user_permissions.project_ids_visible_for_user:
            raise exceptions.NotFound("Project not found.")
        validated_data["project_id"] = self.context["project_id"]
        serializers.raise_errors_on_nested_writes("create", self, validated_data)

        if "week_start_day" not in validated_data:
            country_code = get_geoip_properties(get_ip_address(request)).get("$geoip_country_code", None)
            if country_code:
                week_start_day_for_user_ip_location = get_week_start_for_country_code(country_code)
                # get_week_start_for_country_code() also returns 6 for countries where the week starts on Saturday,
                # but ClickHouse doesn't support Saturday as the first day of the week, so we fall back to Sunday
                validated_data["week_start_day"] = 1 if week_start_day_for_user_ip_location == 1 else 0

        team = Team.objects.create_with_data(
            initiating_user=request.user,
            organization=self.context["view"].organization,
            **validated_data,
        )

        request.user.current_team = team
        request.user.team = request.user.current_team  # Update cached property
        request.user.save()

        log_activity(
            organization_id=team.organization_id,
            team_id=team.pk,
            user=request.user,
            was_impersonated=is_impersonated_session(request),
            scope="Team",
            item_id=team.pk,
            activity="created",
            detail=Detail(name=str(team.name)),
        )

        return team

    def update(self, instance: Team, validated_data: dict[str, Any]) -> Team:
        before_update = instance.__dict__.copy()

        if (
            "session_replay_config" in validated_data
            and validated_data["session_replay_config"] is not None
            and instance.session_replay_config is not None
        ):
            # for session_replay_config and its top level keys we merge existing settings with new settings
            # this way we don't always have to receive the entire settings object to change one setting
            # so for each key in validated_data["session_replay_config"] we merge it with the existing settings
            # and then merge any top level keys that weren't provided

            for key, value in validated_data["session_replay_config"].items():
                if key in instance.session_replay_config:
                    # if they're both dicts then we merge them, otherwise, the new value overwrites the old
                    if isinstance(instance.session_replay_config[key], dict) and isinstance(
                        validated_data["session_replay_config"][key], dict
                    ):
                        validated_data["session_replay_config"][key] = {
                            **instance.session_replay_config[key],  # existing values
                            **value,  # and new values on top
                        }

            # then also add back in any keys that exist but are not in the provided data
            validated_data["session_replay_config"] = {
                **instance.session_replay_config,
                **validated_data["session_replay_config"],
            }

        updated_team = super().update(instance, validated_data)
        changes = dict_changes_between("Team", before_update, updated_team.__dict__, use_field_exclusions=True)

        log_activity(
            organization_id=cast(UUIDT, instance.organization_id),
            team_id=instance.pk,
            user=cast(User, self.context["request"].user),
            was_impersonated=is_impersonated_session(request),
            scope="Team",
            item_id=instance.pk,
            activity="updated",
            detail=Detail(
                name=str(instance.name),
                changes=changes,
            ),
        )

        return updated_team


class TeamViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Projects for the current organization.
    """

    scope_object: APIScopeObjectOrNotSupported = "project"  # TODO: Change to `environment` on environments rollout
    serializer_class = TeamSerializer
    queryset = Team.objects.all().select_related("organization")
    lookup_field = "id"
    ordering = "-created_by"

    def safely_get_queryset(self, queryset):
        # IMPORTANT: This is actually what ensures that a user cannot read/update a project for which they don't have permission
        visible_teams_ids = UserPermissions(cast(User, self.request.user)).team_ids_visible_for_user
        return queryset.filter(id__in=visible_teams_ids)

    def get_serializer_class(self) -> type[serializers.BaseSerializer]:
        if self.action == "list":
            return TeamBasicSerializer
        return super().get_serializer_class()

    # NOTE: Team permissions are somewhat complex so we override the underlying viewset's get_permissions method
    def dangerously_get_permissions(self) -> list:
        """
        Special permissions handling for create requests as the organization is inferred from the current user.
        """

        permissions: list = [
            IsAuthenticated,
            APIScopePermission,
            PremiumMultiProjectPermissions,
            *self.permission_classes,
        ]

        # Return early for non-actions (e.g. OPTIONS)
        if self.action:
            if self.action == "create":
                if "is_demo" not in self.request.data or not self.request.data["is_demo"]:
                    permissions.append(OrganizationAdminWritePermissions)
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
        team_id = team.pk
        organization_id = team.organization_id
        team_name = team.name

        user = cast(User, self.request.user)

        delete_bulky_postgres_data(team_ids=[team_id])
        delete_batch_exports(team_ids=[team_id])

        with mute_selected_signals():
            super().perform_destroy(team)

        # Once the project is deleted, queue deletion of associated data
        AsyncDeletion.objects.bulk_create(
            [
                AsyncDeletion(
                    deletion_type=DeletionType.Team,
                    team_id=team_id,
                    key=str(team_id),
                    created_by=user,
                )
            ],
            ignore_conflicts=True,
        )

        log_activity(
            organization_id=cast(UUIDT, organization_id),
            team_id=team_id,
            user=user,
            was_impersonated=is_impersonated_session(self.request),
            scope="Team",
            item_id=team_id,
            activity="deleted",
            detail=Detail(name=str(team_name)),
        )
        # TRICKY: We pass in `team` here as access to `user.current_team` can fail if it was deleted
        report_user_action(user, f"team deleted", team=team)

    @action(
        methods=["PATCH"],
        detail=True,
        # Only ADMIN or higher users are allowed to access this project
        permission_classes=[TeamMemberStrictManagementPermission],
    )
    def reset_token(self, request: request.Request, id: str, **kwargs) -> response.Response:
        team = self.get_object()
        team.reset_token_and_save(user=request.user, is_impersonated_session=is_impersonated_session(request))
        return response.Response(TeamSerializer(team, context=self.get_serializer_context()).data)

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

    @cached_property
    def user_permissions(self):
        team = self.get_object() if self.action == "reset_token" else None
        return UserPermissions(cast(User, self.request.user), team)


class RootTeamViewSet(TeamViewSet):
    # NOTE: We don't want people creating environments via the "current_organization"/"current_project" concept, but
    # rather specify the org ID and project ID in the URL - hence this is hidden from the API docs, but used in the app
    hide_api_docs = True


def validate_team_attrs(
    attrs: dict[str, Any], view: TeamAndOrgViewSetMixin, request: request.Request, instance: Optional[Team | Project]
) -> dict[str, Any]:
    if "primary_dashboard" in attrs:
        if not instance:
            raise exceptions.ValidationError(
                {"primary_dashboard": "Primary dashboard cannot be set on project creation."}
            )
        if attrs["primary_dashboard"].team_id != instance.id:
            raise exceptions.ValidationError({"primary_dashboard": "Dashboard does not belong to this team."})

    if "access_control" in attrs:
        assert isinstance(request.user, User)
        # We get the instance's organization_id, unless we're handling creation, in which case there's no instance yet
        organization_id = instance.organization_id if instance is not None else cast(UUID | str, view.organization_id)
        # Only organization-wide admins and above should be allowed to switch the project between open and private
        # If a project-only admin who is only an org member disabled this it, they wouldn't be able to reenable it
        org_membership: OrganizationMembership = OrganizationMembership.objects.only("level").get(
            organization_id=organization_id, user=request.user
        )
        if org_membership.level < OrganizationMembership.Level.ADMIN:
            raise exceptions.PermissionDenied(
                "Your organization access level is insufficient to configure project access restrictions."
            )

    if "autocapture_exceptions_errors_to_ignore" in attrs:
        if not isinstance(attrs["autocapture_exceptions_errors_to_ignore"], list):
            raise exceptions.ValidationError("Must provide a list for field: autocapture_exceptions_errors_to_ignore.")
        for error in attrs["autocapture_exceptions_errors_to_ignore"]:
            if not isinstance(error, str):
                raise exceptions.ValidationError(
                    "Must provide a list of strings to field: autocapture_exceptions_errors_to_ignore."
                )

        if len(json.dumps(attrs["autocapture_exceptions_errors_to_ignore"])) > 300:
            raise exceptions.ValidationError(
                "Field autocapture_exceptions_errors_to_ignore must be less than 300 characters. Complex config should be provided in posthog-js initialization."
            )
    return attrs
