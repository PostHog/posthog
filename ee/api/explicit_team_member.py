from typing import Any, Dict, cast

from django.db.utils import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import exceptions, serializers, viewsets
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated

from ee.models.explicit_team_membership import ExplicitTeamMembership
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User


def get_ephemeral_requesting_team_membership(team: Team, user: User) -> ExplicitTeamMembership:
    requesting_parent_membership: OrganizationMembership = OrganizationMembership.objects.get(
        organization_id=team.organization_id, user=user
    )
    try:
        return ExplicitTeamMembership.objects.select_related(
            "team", "parent_membership", "parent_membership__user"
        ).get(team=team, parent_membership=requesting_parent_membership)
    except ExplicitTeamMembership.DoesNotExist:
        # If there's no explicit team membership, we instantiate an ephemeral one just for validation
        return ExplicitTeamMembership(
            team=team, parent_membership=requesting_parent_membership, level=requesting_parent_membership.level
        )


class TeamMemberObjectPermissions(BasePermission):
    """
        Require effective project membership for any access at all,
        and at least admin effective project access level for write/delete.
    """

    message = "You don't have sufficient permissions in this project."

    def has_permission(self, request, view) -> bool:
        try:
            team = Team.objects.get(id=view.get_parents_query_dict()["team_id"])
        except Team.DoesNotExist:
            return True  # This will be handled as a 404 in the viewset
        try:
            requesting_team_membership = get_ephemeral_requesting_team_membership(team, cast(User, request.user))
        except OrganizationMembership.DoesNotExist:
            return True  # This will be handled as a 404 too
        minimum_level = (
            ExplicitTeamMembership.Level.MEMBER
            if request.method in SAFE_METHODS
            else ExplicitTeamMembership.Level.ADMIN
        )
        return requesting_team_membership.effective_level >= minimum_level


class ExplicitTeamMemberAdditionSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(source="parent_membership.user", read_only=True)
    user_id = serializers.IntegerField(required=True, write_only=True)

    class Meta:
        model = ExplicitTeamMembership
        fields = [
            "id",
            "level",
            "parent_membership_id",
            "joined_at",
            "updated_at",
            "user",
            "user_id",
            "effective_level",
        ]
        read_only_fields = ["id", "parent_membership_id", "joined_at", "updated_at", "user", "effective_level"]

    def create(self, validated_data):
        team: Team = self.context["team"]
        user_id = validated_data.pop("user_id")
        validated_data["team"] = team
        try:
            requesting_parent_membership: OrganizationMembership = OrganizationMembership.objects.get(
                organization_id=team.organization_id, user_id=user_id
            )
        except OrganizationMembership.DoesNotExist:
            raise exceptions.PermissionDenied("You both need to belong to the same organization.")
        validated_data["parent_membership"] = requesting_parent_membership
        try:
            return super().create(validated_data)
        except IntegrityError:
            raise exceptions.ValidationError("This user likely already is an explicit member of the project.")

    def validate(self, attrs):
        requesting_user = self.context["request"].user
        try:
            requesting_membership = get_ephemeral_requesting_team_membership(self.context["team"], requesting_user)
        except OrganizationMembership.DoesNotExist:
            # User does not belong to the project's organization, so we spoof a 404 for enhanced security
            raise exceptions.NotFound("Project not found.")
        new_level = attrs.get("level")

        if attrs["user_id"] == requesting_user.id:
            raise exceptions.PermissionDenied("You can't explicitly add yourself to projects.")
        if new_level is not None and new_level > requesting_membership.effective_level:
            raise exceptions.PermissionDenied("You can only set access level to lower or equal to your current one.")
        return attrs


class ExplicitTeamMemberSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(source="parent_membership.user", read_only=True)

    class Meta:
        model = ExplicitTeamMembership
        fields = ["id", "level", "parent_membership_id", "joined_at", "updated_at", "user", "effective_level"]
        read_only_fields = ["id", "joined_at", "parent_membership_id", "updated_at", "effective_level"]

    def validate(self, attrs):
        # We know membership_being_accessed exists since this serializer is specifically not used for creates
        membership_being_accessed = cast(ExplicitTeamMembership, self.instance)
        try:
            requesting_membership = get_ephemeral_requesting_team_membership(
                self.context["team"], self.context["request"].user
            )
        except OrganizationMembership.DoesNotExist:
            # User does not belong to the project's organization, so we spoof a 404 for enhanced security
            raise exceptions.NotFound("Project not found.")
        new_level = attrs.get("level")

        if new_level is not None and new_level > requesting_membership.effective_level:
            raise exceptions.PermissionDenied("You can only set access level to lower or equal to your current one.")
        if membership_being_accessed.parent_membership.user_id != requesting_membership.parent_membership.user_id:
            # Updating someone else
            if membership_being_accessed.team.organization_id != requesting_membership.team.organization_id:
                raise exceptions.PermissionDenied("You both need to belong to the same organization.")
            if membership_being_accessed.level > requesting_membership.effective_level:
                raise exceptions.PermissionDenied("You can only edit others with level lower or equal to you.")
        else:
            if new_level is not None:
                raise exceptions.PermissionDenied("You can't set your own access level.")
        return attrs


class ExplicitTeamMemberViewSet(
    StructuredViewSetMixin, viewsets.ModelViewSet,
):
    permission_classes = [IsAuthenticated, TeamMemberObjectPermissions]
    pagination_class = None
    queryset = ExplicitTeamMembership.objects.select_related("team", "parent_membership", "parent_membership__user")
    lookup_field = "parent_membership__user_id"
    ordering = ["level", "-joined_at"]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ExplicitTeamMemberAdditionSerializer
        return ExplicitTeamMemberSerializer

    def get_serializer_context(self) -> Dict[str, Any]:
        serializer_context = super().get_serializer_context()
        try:
            serializer_context["team"] = Team.objects.get(id=serializer_context["team_id"])
        except Team.DoesNotExist:
            raise exceptions.NotFound("Project not found.")
        return serializer_context

    def get_object(self) -> ExplicitTeamMembership:
        queryset = self.filter_queryset(self.get_queryset())
        lookup_value = self.kwargs[self.lookup_field]
        if lookup_value == "@me":
            return queryset.get(user=self.request.user)
        filter_kwargs = {self.lookup_field: lookup_value}
        obj = get_object_or_404(queryset, **filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj
