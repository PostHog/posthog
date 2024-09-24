from typing import Any, Optional, cast

import posthoganalytics
from rest_framework import (
    exceptions,
    mixins,
    request,
    response,
    serializers,
    status,
    viewsets,
)

from ee.models.explicit_team_membership import ExplicitTeamMembership
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.email import is_email_available
from posthog.event_usage import report_bulk_invited, report_team_member_invited
from posthog.models import OrganizationInvite, OrganizationMembership
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.tasks.email import send_invite


class OrganizationInviteSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    send_email = serializers.BooleanField(write_only=True, default=True)

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

    def validate_private_project_access(
        self, private_project_access: Optional[list[dict[str, Any]]]
    ) -> Optional[list[dict[str, Any]]]:
        team_error = "Team does not exist on this organization, or it is private and you do not have access to it."
        if not private_project_access:
            return None
        for item in private_project_access:
            # if the project is private, if user is not an admin of the team, they can't invite to it
            organization: Organization = Organization.objects.get(id=self.context["organization_id"])
            if not organization:
                raise exceptions.ValidationError("Organization not found.")
            teams = organization.teams.all()
            try:
                team: Team = teams.get(id=item["id"])
            except Team.DoesNotExist:
                raise exceptions.ValidationError(
                    team_error,
                )
            is_private = team.access_control
            if not is_private:
                continue
            try:
                explicit_team_membership: ExplicitTeamMembership = ExplicitTeamMembership.objects.get(
                    team_id=item["id"],
                    parent_membership__user=self.context["request"].user,
                )
            except ExplicitTeamMembership.DoesNotExist:
                raise exceptions.ValidationError(
                    team_error,
                )
            if explicit_team_membership.level < item["level"]:
                raise exceptions.ValidationError(
                    "You cannot invite to a private project with a higher level than your own.",
                )

        return private_project_access

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> OrganizationInvite:
        if OrganizationMembership.objects.filter(
            organization_id=self.context["organization_id"],
            user__email=validated_data["target_email"],
        ).exists():
            raise exceptions.ValidationError("A user with this email address already belongs to the organization.")
        send_email = validated_data.pop("send_email", True)
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

    @action(methods=["POST"], detail=False, required_scopes=["organization_member:write"])
    def bulk(self, request: request.Request, **kwargs) -> response.Response:
        data = cast(Any, request.data)
        user = cast(User, self.request.user)
        current_url = request.headers.get("Referer")
        session_id = request.headers.get("X-Posthog-Session-Id")
        if user.distinct_id:
            posthoganalytics.capture(
                user.distinct_id,
                "bulk invite attempted",
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
