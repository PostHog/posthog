from typing import cast

from django.db import transaction

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.user import MAX_PIPELINE_NOTIFICATIONS, PIPELINE_ID_PATTERN
from posthog.dataclasses import frozen
from posthog.models import OrganizationMembership, Team, User
from posthog.permissions import OrganizationAdminReadPermissions, PostHogFeatureFlagPermission

from products.batch_exports.backend.models.batch_export import BatchExport
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.plugin import PluginConfig
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)

ADMIN_PIPELINE_NOTIFICATION_CONTROLS_FLAG = "admin-pipeline-notification-controls"

# Bounds the work one save can do. Well above what the settings page can produce from a single
# project, since it renders one checkbox per pipeline and member pair.
MAX_CHANGES_PER_REQUEST = 1000

NOTIFICATION_SETTINGS_URL = "/settings/user-notifications?highlight=data-pipeline-errors"


@frozen
class _EligibleMember:
    user: User
    membership_level: int
    editable: bool


# The viewset defines a `list` action, which shadows the builtin inside the class body, so
# annotations there go through this alias.
_EligibleMembers = list[_EligibleMember]


class PipelineNotificationMemberSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(help_text="Numeric ID of the member, used as the key when saving changes.")
    uuid = serializers.UUIDField(help_text="Stable public identifier of the member.")
    first_name = serializers.CharField(help_text="Member's first name, for display in the members list.")
    last_name = serializers.CharField(help_text="Member's last name, for display in the members list.")
    email = serializers.EmailField(help_text="Member's email address, which is where pipeline failure emails go.")
    organization_membership_level = serializers.IntegerField(
        help_text="Member's organization membership level: 1 for member, 8 for admin, 15 for owner."
    )
    editable = serializers.BooleanField(
        help_text="False when the member's organization membership level is above yours, which means you cannot change their settings."
    )
    pipeline_emails_enabled = serializers.BooleanField(
        help_text="Whether the member has pipeline failure emails turned on at all. When false, per-pipeline subscriptions have no effect until the member turns their own setting back on."
    )
    unsubscribed_pipeline_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text="Pipeline IDs this member has opted out of. Any pipeline not listed here sends them failure emails.",
    )


class PipelineNotificationChangeSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(help_text="Numeric ID of the member to change.")
    pipeline_id = serializers.RegexField(
        PIPELINE_ID_PATTERN,
        help_text='Pipeline identifier, one of "hog_function:<uuid>", "batch_export:<uuid>", or "plugin_config:<id>".',
    )
    subscribed = serializers.BooleanField(
        help_text="True to send this member failure emails for this pipeline, false to stop sending them."
    )


class PipelineNotificationBulkUpdateSerializer(serializers.Serializer):
    changes = serializers.ListField(
        child=PipelineNotificationChangeSerializer(),
        allow_empty=False,
        max_length=MAX_CHANGES_PER_REQUEST,
        help_text="Only the member and pipeline pairs you changed. Pairs left out keep whatever the member has set, so a member editing their own settings concurrently is not overwritten.",
    )


def _actor_level(user: User, team: Team) -> int:
    # OrganizationAdminReadPermissions has already rejected anyone below admin, so a missing
    # membership here is not reachable through the API.
    membership = OrganizationMembership.objects.filter(user=user, organization_id=team.organization_id).first()
    return membership.level if membership else OrganizationMembership.Level.MEMBER


def _eligible_members(team: Team, actor_level: int) -> _EligibleMembers:
    """Members who can receive this project's pipeline failure emails.

    `all_users_with_access` applies the same project-access rule as `get_members_to_notify`, which
    decides who the emails actually go to, so this list is the real recipient list rather than every
    organization member.
    """
    users_with_access = team.all_users_with_access()
    levels_by_user_id = dict(
        OrganizationMembership.objects.filter(
            organization_id=team.organization_id, user_id__in=users_with_access.values_list("id", flat=True)
        ).values_list("user_id", "level")
    )

    members = []
    for user in users_with_access:
        level = levels_by_user_id.get(user.id)
        if level is None:
            continue
        members.append(_EligibleMember(user=user, membership_level=level, editable=level <= actor_level))
    return sorted(members, key=lambda member: (member.user.email or "").lower())


def _project_pipeline_ids(team: Team) -> set[str]:
    """Pipeline IDs this project owns, in the shape the email senders look them up by.

    `pipeline_notifications_disabled` is one global map per member, shared across every project the
    member belongs to. Without this set, a pipeline ID from another project would read and write
    through this project's endpoint.
    """
    return {
        *(f"hog_function:{pk}" for pk in HogFunction.objects.filter(team_id=team.id).values_list("id", flat=True)),
        *(f"batch_export:{pk}" for pk in BatchExport.objects.filter(team_id=team.id).values_list("id", flat=True)),
        *(f"plugin_config:{pk}" for pk in PluginConfig.objects.filter(team_id=team.id).values_list("id", flat=True)),
    }


def _represent(member: _EligibleMember, project_pipeline_ids: set[str]) -> dict:
    settings = member.user.notification_settings
    unsubscribed = settings.get("pipeline_notifications_disabled") or {}
    return {
        "user_id": member.user.id,
        "uuid": member.user.uuid,
        "first_name": member.user.first_name,
        "last_name": member.user.last_name,
        "email": member.user.email,
        "organization_membership_level": member.membership_level,
        "editable": member.editable,
        "pipeline_emails_enabled": settings.get("plugin_disabled", True),
        "unsubscribed_pipeline_ids": sorted(
            pipeline_id
            for pipeline_id, disabled in unsubscribed.items()
            if disabled and pipeline_id in project_pipeline_ids
        ),
    }


def _apply_changes(user: User, pipeline_changes: dict[str, bool]) -> None:
    partial = dict(user.partial_notification_settings or {})
    unsubscribed = dict(partial.get("pipeline_notifications_disabled") or {})
    for pipeline_id, subscribed in pipeline_changes.items():
        if subscribed:
            unsubscribed.pop(pipeline_id, None)
        else:
            unsubscribed[pipeline_id] = True

    if len(unsubscribed) > MAX_PIPELINE_NOTIFICATIONS:
        raise serializers.ValidationError(
            f"{user.email} cannot have more than {MAX_PIPELINE_NOTIFICATIONS} muted pipelines",
            code="invalid_input",
        )

    partial["pipeline_notifications_disabled"] = unsubscribed
    user.partial_notification_settings = partial
    user.save(update_fields=["partial_notification_settings"])


def _notify(team: Team, user: User, pipeline_changes: dict[str, bool]) -> None:
    count = len(pipeline_changes)
    pipelines = "1 pipeline" if count == 1 else f"{count} pipelines"
    subscribed_count = sum(1 for subscribed in pipeline_changes.values() if subscribed)
    if subscribed_count == count:
        body = f"An admin turned on data pipeline failure emails for you for {pipelines} in {team.name}."
    elif subscribed_count == 0:
        body = f"An admin turned off data pipeline failure emails for you for {pipelines} in {team.name}."
    else:
        body = f"An admin changed your data pipeline failure emails for {pipelines} in {team.name}."

    create_notification(
        NotificationData(
            team_id=team.id,
            notification_type=NotificationType.NOTIFICATION_SETTINGS_CHANGED,
            priority=Priority.NORMAL,
            title="Your notification settings changed",
            body=f"{body} You can change them back in Settings, under Account, Notifications.",
            target_type=TargetType.USER,
            target_id=str(user.id),
            source_url=NOTIFICATION_SETTINGS_URL,
        )
    )


@extend_schema(extensions={"x-product": "core"})
class PipelineNotificationSubscriptionViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"
    permission_classes = [OrganizationAdminReadPermissions, PostHogFeatureFlagPermission]
    posthog_feature_flag = ADMIN_PIPELINE_NOTIFICATION_CONTROLS_FLAG
    pagination_class = None

    @extend_schema(
        responses={200: PipelineNotificationMemberSerializer(many=True)},
        description="List the members who can receive data pipeline failure emails for this project, along with the pipelines each one has opted out of.",
    )
    def list(self, request: Request, **kwargs) -> Response:
        project_pipeline_ids = _project_pipeline_ids(self.team)
        return Response([_represent(member, project_pipeline_ids) for member in self._members()])

    @extend_schema(
        request=PipelineNotificationBulkUpdateSerializer,
        responses={200: PipelineNotificationMemberSerializer(many=True)},
        description="Subscribe or unsubscribe members from data pipeline failure emails for this project's pipelines. Each affected member is notified in the app that their settings changed.",
    )
    @action(methods=["POST"], detail=False, url_path="bulk_update")
    def bulk_update(self, request: Request, **kwargs) -> Response:
        serializer = PipelineNotificationBulkUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        project_pipeline_ids = _project_pipeline_ids(self.team)
        members_by_id = {member.user.id: member for member in self._members()}
        changes_by_user: dict[int, dict[str, bool]] = {}
        for change in serializer.validated_data["changes"]:
            member = members_by_id.get(change["user_id"])
            if member is None:
                raise serializers.ValidationError(
                    f"User {change['user_id']} is not a member with access to this project",
                    code="invalid_input",
                )
            if not member.editable:
                raise PermissionDenied(
                    f"Your organization access level is insufficient to change settings for {member.user.email}"
                )
            if change["pipeline_id"] not in project_pipeline_ids:
                raise serializers.ValidationError(
                    f"Pipeline {change['pipeline_id']} does not belong to this project",
                    code="invalid_input",
                )
            changes_by_user.setdefault(member.user.id, {})[change["pipeline_id"]] = change["subscribed"]

        with transaction.atomic():
            # Re-read under the lock so a concurrent write to the same member's settings, by
            # themselves or by another admin, is merged rather than dropped.
            locked_users = {
                user.id: user for user in User.objects.select_for_update().filter(id__in=changes_by_user.keys())
            }
            for user_id, pipeline_changes in changes_by_user.items():
                _apply_changes(locked_users[user_id], pipeline_changes)

        for user_id, pipeline_changes in changes_by_user.items():
            _notify(self.team, members_by_id[user_id].user, pipeline_changes)

        return Response([_represent(member, project_pipeline_ids) for member in self._members()])

    def _members(self) -> _EligibleMembers:
        user = cast(User, self.request.user)
        return _eligible_members(self.team, _actor_level(user, self.team))
