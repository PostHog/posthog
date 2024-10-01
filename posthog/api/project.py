from datetime import timedelta
from functools import cached_property
from typing import Any, Optional, cast

from django.shortcuts import get_object_or_404
from loginas.utils import is_impersonated_session
from rest_framework import exceptions, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from posthog.geoip import get_geoip_properties
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import ProjectBackwardCompatBasicSerializer
from posthog.api.team import PremiumMultiProjectPermissions, TeamSerializer, validate_team_attrs
from posthog.event_usage import report_user_action
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import User
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
    APIScopePermission,
    OrganizationAdminWritePermissions,
    OrganizationMemberPermissions,
    TeamMemberLightManagementPermission,
    TeamMemberStrictManagementPermission,
)
from posthog.user_permissions import UserPermissions, UserPermissionsSerializerMixin
from posthog.utils import get_ip_address, get_week_start_for_country_code


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ["id", "organization_id", "name", "created_at"]
        read_only_fields = ["id", "organization_id", "created_at"]


class ProjectBackwardCompatSerializer(ProjectBackwardCompatBasicSerializer, UserPermissionsSerializerMixin):
    effective_membership_level = serializers.SerializerMethodField()  # Compat with TeamSerializer
    has_group_types = serializers.SerializerMethodField()  # Compat with TeamSerializer
    live_events_token = serializers.SerializerMethodField()  # Compat with TeamSerializer

    class Meta:
        model = Project
        fields = (
            "id",
            "organization",
            "name",
            "created_at",
            "effective_membership_level",  # Compat with TeamSerializer
            "has_group_types",  # Compat with TeamSerializer
            "live_events_token",  # Compat with TeamSerializer
            "updated_at",
            "uuid",  # Compat with TeamSerializer
            "api_token",  # Compat with TeamSerializer
            "app_urls",  # Compat with TeamSerializer
            "slack_incoming_webhook",  # Compat with TeamSerializer
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
            "session_replay_config",  # Compat with TeamSerializer
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
        )
        read_only_fields = (
            "id",
            "uuid",
            "organization",
            "effective_membership_level",
            "has_group_types",
            "live_events_token",
            "created_at",
            "api_token",
            "updated_at",
            "ingested_event",
            "default_modifiers",
            "person_on_events_querying_enabled",
        )

        team_passthrough_fields = {
            "updated_at",
            "uuid",
            "api_token",
            "app_urls",
            "slack_incoming_webhook",
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
        }

    def get_effective_membership_level(self, project: Project) -> Optional[OrganizationMembership.Level]:
        team = project.teams.get(pk=project.pk)
        return self.user_permissions.team(team).effective_membership_level

    def get_has_group_types(self, project: Project) -> bool:
        return GroupTypeMapping.objects.filter(team_id=project.id).exists()

    def get_live_events_token(self, project: Project) -> Optional[str]:
        team = project.teams.get(pk=project.pk)
        return encode_jwt(
            {"team_id": team.id, "api_token": team.api_token},
            timedelta(days=7),
            PosthogJwtAudience.LIVESTREAM,
        )

    @staticmethod
    def validate_session_recording_linked_flag(value) -> dict | None:
        return TeamSerializer.validate_session_recording_linked_flag(value)

    @staticmethod
    def validate_session_recording_network_payload_capture_config(value) -> dict | None:
        return TeamSerializer.validate_session_recording_network_payload_capture_config(value)

    @staticmethod
    def validate_session_replay_config(value) -> dict | None:
        return TeamSerializer.validate_session_replay_config(value)

    @staticmethod
    def validate_session_replay_ai_summary_config(value: dict | None) -> dict | None:
        return TeamSerializer.validate_session_replay_ai_summary_config(value)

    def validate(self, attrs: Any) -> Any:
        attrs = validate_team_attrs(attrs, self.context["view"], self.context["request"], self.instance)
        return super().validate(attrs)

    def create(self, validated_data: dict[str, Any], **kwargs) -> Project:
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
            was_impersonated=is_impersonated_session(request),
            scope="Project",
            item_id=project.pk,
            activity="created",
            detail=Detail(name=str(project.name)),
        )
        log_activity(
            organization_id=project.organization_id,
            team_id=team.pk,
            user=request.user,
            was_impersonated=is_impersonated_session(request),
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

        should_team_be_saved_too = False
        for attr, value in validated_data.items():
            if attr in self.Meta.team_passthrough_fields:
                should_team_be_saved_too = True
                setattr(team, attr, value)
            else:
                if attr == "name":  # `name` should be updated on _both_ the Project and Team
                    should_team_be_saved_too = True
                    setattr(team, attr, value)
                setattr(instance, attr, value)

        instance.save()
        if should_team_be_saved_too:
            team.save()

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
                was_impersonated=is_impersonated_session(request),
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
                was_impersonated=is_impersonated_session(request),
                scope="Project",
                item_id=instance.pk,
                activity="updated",
                detail=Detail(
                    name=str(instance.name),
                    changes=project_changes,
                ),
            )

        return instance


class ProjectViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Projects for the current organization.
    """

    scope_object: APIScopeObjectOrNotSupported = "project"
    serializer_class = ProjectBackwardCompatSerializer
    queryset = Project.objects.all().select_related("organization").prefetch_related("teams")
    lookup_field = "id"
    ordering = "-created_by"

    def safely_get_queryset(self, queryset):
        # IMPORTANT: This is actually what ensures that a user cannot read/update a project for which they don't have permission
        visible_teams_ids = UserPermissions(cast(User, self.request.user)).team_ids_visible_for_user
        return queryset.filter(id__in=visible_teams_ids)

    def get_serializer_class(self) -> type[serializers.BaseSerializer]:
        if self.action == "list":
            return ProjectBackwardCompatBasicSerializer
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
        project_id = project.pk
        organization_id = project.organization_id
        project_name = project.name

        user = cast(User, self.request.user)

        teams = list(project.teams.only("id", "uuid", "name", "organization_id").all())
        delete_bulky_postgres_data(team_ids=[team.id for team in teams])
        delete_batch_exports(team_ids=[team.id for team in teams])

        with mute_selected_signals():
            super().perform_destroy(project)

        # Once the project is deleted, queue deletion of associated data
        AsyncDeletion.objects.bulk_create(
            [
                AsyncDeletion(
                    deletion_type=DeletionType.Team,
                    team_id=team.id,
                    key=str(team.id),
                    created_by=user,
                )
                for team in teams
            ],
            ignore_conflicts=True,
        )

        for team in teams:
            log_activity(
                organization_id=cast(UUIDT, organization_id),
                team_id=team.pk,
                user=user,
                was_impersonated=is_impersonated_session(self.request),
                scope="Team",
                item_id=team.pk,
                activity="deleted",
                detail=Detail(name=str(team.name)),
            )
            report_user_action(user, f"team deleted", team=team)
        log_activity(
            organization_id=cast(UUIDT, organization_id),
            team_id=project_id,
            user=user,
            was_impersonated=is_impersonated_session(self.request),
            scope="Project",
            item_id=project_id,
            activity="deleted",
            detail=Detail(name=str(project_name)),
        )
        report_user_action(
            user,
            f"project deleted",
            {"project_name": project_name},
            team=teams[0],
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
            user=request.user, is_impersonated_session=is_impersonated_session(request)
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

    @cached_property
    def user_permissions(self):
        project = self.get_object() if self.action == "reset_token" else None
        team = project.passthrough_team if project else None
        return UserPermissions(cast(User, self.request.user), team)


class RootProjectViewSet(ProjectViewSet):
    # NOTE: We don't want people creating projects via the "current_organization" concept, but rather specify the org ID
    # in the URL - hence this is hidden from the API docs, but used in the app
    hide_api_docs = True
