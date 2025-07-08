from datetime import datetime, timedelta
from typing import Any, Optional, cast
from uuid import UUID

import posthoganalytics
from django.db.models import QuerySet
from rest_framework import exceptions, mixins, request, response, serializers, status, viewsets, permissions

from ee.models.explicit_team_membership import ExplicitTeamMembership
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.constants import INVITE_DAYS_VALIDITY
from posthog.email import is_email_available
from posthog.event_usage import report_bulk_invited, report_team_member_invited
from posthog.models import OrganizationInvite, OrganizationMembership
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.tasks.email import send_invite
from posthog.permissions import UserCanInvitePermission, OrganizationMemberPermissions


class OrganizationInviteManager:
    @staticmethod
    def combine_invites(
        organization_id: UUID | str, validated_data: dict[str, Any], combine_pending_invites: bool = True
    ) -> dict[str, Any]:
        """Combines multiple pending invites for the same email address."""
        if not combine_pending_invites:
            return validated_data

        existing_invites = OrganizationInviteManager._get_invites_for_user_org(
            organization_id=organization_id, target_email=validated_data["target_email"]
        )

        if not existing_invites.exists():
            return validated_data

        validated_data["level"] = OrganizationInviteManager._get_highest_level(
            existing_invites=existing_invites,
            new_level=validated_data.get("level", OrganizationMembership.Level.MEMBER),
        )

        validated_data["private_project_access"] = OrganizationInviteManager._combine_project_access(
            existing_invites=existing_invites, new_access=validated_data.get("private_project_access", [])
        )

        return validated_data

    @staticmethod
    def _get_invites_for_user_org(
        organization_id: UUID | str, target_email: str, include_expired: bool = False
    ) -> QuerySet:
        filters: dict[str, Any] = {
            "organization_id": organization_id,
            "target_email": target_email,
        }

        if not include_expired:
            filters["created_at__gt"] = datetime.now() - timedelta(days=INVITE_DAYS_VALIDITY)

        return OrganizationInvite.objects.filter(**filters).order_by("-created_at")

    @staticmethod
    def _get_highest_level(existing_invites: QuerySet, new_level: int) -> int:
        levels = [invite.level for invite in existing_invites]
        levels.append(new_level)
        return max(levels)

    @staticmethod
    def _combine_project_access(existing_invites: QuerySet, new_access: list[dict]) -> list[dict]:
        combined_access: dict[int, int] = {}

        # Add new access first
        for access in new_access:
            combined_access[access["id"]] = access["level"]

        # Combine with existing access, keeping highest levels
        for invite in existing_invites:
            if not invite.private_project_access:
                continue

            for access in invite.private_project_access:
                project_id = access["id"]
                if project_id not in combined_access or access["level"] > combined_access[project_id]:
                    combined_access[project_id] = access["level"]

        return [{"id": project_id, "level": level} for project_id, level in combined_access.items()]

    @staticmethod
    def delete_existing_invites(organization_id: UUID | str, target_email: str) -> None:
        """Deletes all existing invites for a given email in an organization."""
        OrganizationInviteManager._get_invites_for_user_org(
            organization_id=organization_id, target_email=target_email, include_expired=True
        ).delete()


class OrganizationInviteSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    send_email = serializers.BooleanField(write_only=True, default=True)
    combine_pending_invites = serializers.BooleanField(write_only=True, default=False)

    class Meta:
        model = OrganizationInvite
        fields = [
            "id",
            "target_email",
            "first_name",
            "emailing_attempt_made",
            "level",
            "is_expired",
            "created_by",
            "created_at",
            "updated_at",
            "message",
            "private_project_access",
            "send_email",
            "combine_pending_invites",
        ]
        read_only_fields = [
            "id",
            "emailing_attempt_made",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {"target_email": {"required": True, "allow_null": False}}

    def validate_target_email(self, email: str):
        local_part, domain = email.split("@")
        return f"{local_part}@{domain.lower()}"

    def validate_level(self, level: int) -> int:
        # Validate that the user can't invite someone with a higher permission level than their own
        try:
            user_membership = OrganizationMembership.objects.get(
                organization_id=self.context["organization_id"],
                user=self.context["request"].user,
            )
            if level > user_membership.level:
                raise exceptions.PermissionDenied(
                    "You cannot invite a user with a higher permission level than your own."
                )
        except OrganizationMembership.DoesNotExist:
            # This should not happen in normal operation, but we'll handle it just in case
            raise exceptions.PermissionDenied("You must be a member of the organization to send invites.")

        return level

    def validate_private_project_access(
        self, private_project_access: Optional[list[dict[str, Any]]]
    ) -> Optional[list[dict[str, Any]]]:
        team_error = "Project does not exist on this organization, or it is private and you do not have access to it."
        if not private_project_access:
            return None

        # Note: this validation is checking if the inviting user has permission to invite others to the project with the specified access level, not whether the project itself has access controls enabled.
        # checking if the inviting user has permission to invite a user to the project with the given level
        for item in private_project_access:
            # if the project is private, if user is not an admin of the team, they can't invite to it
            organization: Organization = Organization.objects.get(id=self.context["organization_id"])
            if not organization:
                raise exceptions.ValidationError("Organization not found.")
            teams = organization.teams.all()
            try:
                team: Team = teams.get(id=item["id"])
            except Team.DoesNotExist:
                raise exceptions.ValidationError(team_error)

            try:
                # Check if the user is an org admin/owner - org admins/owners can invite with any level
                OrganizationMembership.objects.get(
                    organization_id=self.context["organization_id"],
                    user=self.context["request"].user,
                    level__in=[OrganizationMembership.Level.ADMIN, OrganizationMembership.Level.OWNER],
                )
                continue
            except OrganizationMembership.DoesNotExist:
                # User is not an org admin/owner
                pass

            # This path is deprecated, and will be removed soon
            if team.access_control:
                team_membership: ExplicitTeamMembership | None = None
                try:
                    team_membership = ExplicitTeamMembership.objects.get(
                        team_id=item["id"],
                        parent_membership__user=self.context["request"].user,
                    )
                except ExplicitTeamMembership.DoesNotExist:
                    raise exceptions.ValidationError(team_error)
                if team_membership.level < item["level"]:
                    raise exceptions.ValidationError(
                        "You cannot invite to a private project with a higher level than your own.",
                    )
                # Legacy private project and the current user has permission to invite to it
                continue

            # New access control checks
            from ee.models.rbac.access_control import AccessControl

            # Check if the team has an access control row that applies to the entire resource
            team_access_controls = AccessControl.objects.filter(
                team_id=item["id"],
                resource="team",
                resource_id=str(item["id"]),
                organization_member=None,
                role=None,
            )

            # If no access controls exist, continue (team can be accessed by anyone in the organization)
            if not team_access_controls.exists():
                continue

            # Check if there's an access control with level 'none' (private team)
            private_team_access = team_access_controls.filter(access_level="none").exists()

            if private_team_access:
                # Team is private, check if user has admin access
                user_access = AccessControl.objects.filter(
                    team_id=item["id"],
                    resource="team",
                    resource_id=str(item["id"]),
                    organization_member__user=self.context["request"].user,
                    access_level="admin",
                ).exists()

                if not user_access:
                    raise exceptions.ValidationError(team_error)

        return private_project_access

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> OrganizationInvite:
        if OrganizationMembership.objects.filter(
            organization_id=self.context["organization_id"],
            user__email=validated_data["target_email"],
        ).exists():
            raise exceptions.ValidationError("A user with this email address already belongs to the organization.")

        combine_pending_invites = validated_data.pop("combine_pending_invites", False)
        send_email = validated_data.pop("send_email", True)

        # Handle invite combination if requested
        if combine_pending_invites:
            validated_data = OrganizationInviteManager.combine_invites(
                organization_id=self.context["organization_id"],
                validated_data=validated_data,
                combine_pending_invites=True,
            )

        # Delete existing invites for this email
        OrganizationInviteManager.delete_existing_invites(
            organization_id=self.context["organization_id"], target_email=validated_data["target_email"]
        )

        # Create new invite
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            organization_id=self.context["organization_id"],
            created_by=self.context["request"].user,
            **validated_data,
        )

        if is_email_available(with_absolute_urls=True) and send_email:
            invite.emailing_attempt_made = True
            send_invite(invite_id=invite.id)
            invite.save()

        report_team_member_invited(
            self.context["request"].user,
            invite_id=str(invite.id),
            name_provided=bool(validated_data.get("first_name")),
            current_invite_count=invite.organization.active_invites.count(),
            current_member_count=OrganizationMembership.objects.filter(
                organization_id=self.context["organization_id"],
            ).count(),
            is_bulk=self.context.get("bulk_create", False),
            email_available=is_email_available(with_absolute_urls=True),
            current_url=self.context.get("current_url"),
            session_id=self.context.get("session_id"),
        )

        return invite


class OrganizationInviteViewSet(
    TeamAndOrgViewSetMixin,
    mixins.DestroyModelMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "organization_member"
    serializer_class = OrganizationInviteSerializer
    queryset = OrganizationInvite.objects.all()
    lookup_field = "id"
    ordering = "-created_at"

    def dangerously_get_permissions(self):
        if self.action == "create":
            create_permissions = [
                permission()
                for permission in [permissions.IsAuthenticated, OrganizationMemberPermissions, UserCanInvitePermission]
            ]

            return create_permissions

        raise NotImplementedError()

    def safely_get_queryset(self, queryset):
        return queryset.select_related("created_by").order_by(self.ordering)

    def lowercase_email_domain(self, email: str):
        # According to the email RFC https://www.rfc-editor.org/rfc/rfc1035, anything before the @ can be
        # case-sensitive but the domain should not be. There have been a small number of customers who type in their emails
        # with a capitalized domain. We shouldn't prevent them from inviting teammates because of this.
        local_part, domain = email.split("@")
        return f"{local_part}@{domain.lower()}"

    def create(self, request: request.Request, **kwargs) -> response.Response:
        data = cast(Any, request.data.copy())

        serializer = OrganizationInviteSerializer(
            data=data,
            context={**self.get_serializer_context()},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return response.Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(
        methods=["POST"],
        detail=False,
        required_scopes=["organization_member:write"],
        permission_classes=[UserCanInvitePermission],
    )
    def bulk(self, request: request.Request, **kwargs) -> response.Response:
        data = cast(Any, request.data)
        user = cast(User, self.request.user)
        current_url = request.headers.get("Referer")
        session_id = request.headers.get("X-Posthog-Session-Id")
        if user.distinct_id:
            posthoganalytics.capture(
                distinct_id=str(user.distinct_id),
                event="bulk invite attempted",
                properties={
                    "invitees_count": len(data),
                    "$current_url": current_url,
                    "$session_id": session_id,
                },
            )
        if not isinstance(data, list):
            raise exceptions.ValidationError("This endpoint needs an array of data for bulk invite creation.")
        if len(data) > 20:
            raise exceptions.ValidationError(
                "A maximum of 20 invites can be sent in a single request.",
                code="max_length",
            )

        serializer = OrganizationInviteSerializer(
            data=data,
            many=True,
            context={
                **self.get_serializer_context(),
                "bulk_create": True,
                "current_url": current_url,
                "session_id": session_id,
            },
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        organization = Organization.objects.get(id=self.organization_id)
        report_bulk_invited(
            cast(User, self.request.user),
            invitee_count=len(serializer.validated_data),
            name_count=sum(1 for invite in serializer.validated_data if invite.get("first_name")),
            current_invite_count=organization.active_invites.count(),
            current_member_count=organization.memberships.count(),
            email_available=is_email_available(),
            current_url=current_url,
            session_id=session_id,
        )

        return response.Response(serializer.data, status=status.HTTP_201_CREATED)
