from typing import Any, Dict, Optional, cast

from django.db.utils import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from ee.models.explicit_team_membership import ExplicitTeamMembership
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User
from posthog.permissions import TeamMemberStrictManagementPermission


class ExplicitTeamMemberSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(source="parent_membership.user", read_only=True)
    parent_level = serializers.IntegerField(source="parent_membership.level", read_only=True)

    user_uuid = serializers.UUIDField(required=True, write_only=True)

    class Meta:
        model = ExplicitTeamMembership
        fields = [
            "id",
            "level",
            "parent_level",
            "parent_membership_id",
            "joined_at",
            "updated_at",
            "user",
            "user_uuid",  # write_only (see above)
            "effective_level",  # read_only (calculated)
        ]
        read_only_fields = ["id", "parent_membership_id", "joined_at", "updated_at", "user", "effective_level"]

    def create(self, validated_data):
        team: Team = self.context["team"]
        user_uuid = validated_data.pop("user_uuid")
        validated_data["team"] = team
        try:
            requesting_parent_membership: OrganizationMembership = OrganizationMembership.objects.get(
                organization_id=team.organization_id, user__uuid=user_uuid, user__is_active=True,
            )
        except OrganizationMembership.DoesNotExist:
            raise exceptions.PermissionDenied("You both need to belong to the same organization.")
        validated_data["parent_membership"] = requesting_parent_membership
        try:
            return super().create(validated_data)
        except IntegrityError:
            raise exceptions.ValidationError("This user likely already is an explicit member of the project.")

    def validate(self, attrs):
        team: Team = self.context["team"]
        if not team.access_control:
            raise exceptions.ValidationError(
                "Explicit members can only be accessed for projects with project-based permissioning enabled."
            )
        requesting_user: User = self.context["request"].user
        membership_being_accessed = cast(Optional[ExplicitTeamMembership], self.instance)
        try:
            requesting_level = self.context["team"].get_effective_membership_level(requesting_user.id)
        except OrganizationMembership.DoesNotExist:
            # Requesting user does not belong to the project's organization, so we spoof a 404 for enhanced security
            raise exceptions.NotFound("Project not found.")

        new_level = attrs.get("level")

        if requesting_level is None:
            raise exceptions.PermissionDenied("You do not have the required access to this project.")

        if attrs.get("user_uuid") == requesting_user.uuid:
            # Create-only check
            raise exceptions.PermissionDenied("You can't explicitly add yourself to projects.")

        if new_level is not None and new_level > requesting_level:
            raise exceptions.PermissionDenied("You can only set access level to lower or equal to your current one.")

        if membership_being_accessed is not None:
            # Update-only checks
            if membership_being_accessed.parent_membership.user_id != requesting_user.id:
                # Requesting user updating someone else
                if membership_being_accessed.level > requesting_level:
                    raise exceptions.PermissionDenied("You can only edit others with level lower or equal to you.")
            else:
                # Requesting user updating themselves
                if new_level is not None:
                    raise exceptions.PermissionDenied("You can't set your own access level.")

        return attrs


class ExplicitTeamMemberViewSet(
    StructuredViewSetMixin, viewsets.ModelViewSet,
):
    permission_classes = [IsAuthenticated, TeamMemberStrictManagementPermission]
    pagination_class = None
    queryset = ExplicitTeamMembership.objects.filter(parent_membership__user__is_active=True).select_related(
        "team", "parent_membership", "parent_membership__user"
    )
    lookup_field = "parent_membership__user__uuid"
    ordering = ["level", "-joined_at"]
    serializer_class = ExplicitTeamMemberSerializer
    include_in_docs = False

    def get_serializer_context(self) -> Dict[str, Any]:
        serializer_context = super().get_serializer_context()
        try:
            serializer_context["team"] = Team.objects.get(id=serializer_context["team_id"])
        except Team.DoesNotExist:
            raise exceptions.NotFound("Project not found.")
        return serializer_context

    def get_permissions(self):
        if (
            self.action == "destroy"
            and self.request.user.is_authenticated
            and self.kwargs.get("parent_membership__user__uuid") == str(self.request.user.uuid)
        ):
            # Special case: allow already authenticated users to leave projects
            return []
        return super().get_permissions()

    def get_object(self) -> ExplicitTeamMembership:
        queryset = self.filter_queryset(self.get_queryset())
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@me":
            return queryset.get(user=self.request.user)
        filter_kwargs = {self.lookup_field: lookup_value}
        obj = get_object_or_404(queryset, **filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj
