"""The organization members page's project access column and modal.

OrganizationMemberProjectAccessViewSetMixin belongs on the organization members viewset only:
/api/organizations/:id/members/project_access. Per-project access management stays on the
project viewset (access_control_settings.py).
"""

from typing import TYPE_CHECKING, cast

from drf_spectacular.utils import OpenApiResponse
from rest_framework import exceptions, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.models import Organization, OrganizationMembership, User

from products.access_control.backend.facade.member_project_access import member_project_access

from .access_control import ResolvedAccessSerializer

if TYPE_CHECKING:
    _GenericViewSet = GenericViewSet
else:
    _GenericViewSet = object


class ProjectAccessSourceSerializer(ResolvedAccessSerializer):
    subject_name = serializers.CharField(
        allow_null=True,
        help_text="The name of the role or member whose rule decided. Null when the default or a bypass decided.",
    )


class MemberProjectAccessEntrySerializer(serializers.Serializer):
    team_id = serializers.IntegerField(help_text="The project's id.")
    team_name = serializers.CharField(help_text="The project's name.")
    access_level = serializers.CharField(
        help_text="The member's enforced access to the project: none, member or admin."
    )
    resolved = ProjectAccessSourceSerializer(
        allow_null=True,
        help_text="The rule that supplies the level. Read `source` and `source_subject` to tell an organization "
        "admin's bypass from a member rule, a role rule or the project default.",
    )
    subject_id = serializers.CharField(
        allow_null=True,
        help_text="The id of the role or organization membership whose rule decided. Null when the default or a "
        "bypass decided.",
    )


class MemberProjectAccessSerializer(serializers.Serializer):
    organization_membership_id = serializers.UUIDField(help_text="The organization membership id.")
    projects = MemberProjectAccessEntrySerializer(
        many=True,
        help_text="One entry per project the caller can access, including projects the member cannot.",
    )


class MemberProjectAccessResponseSerializer(serializers.Serializer):
    results = MemberProjectAccessSerializer(many=True, help_text="One entry per visible organization member.")


class MemberProjectAccessQuerySerializer(serializers.Serializer):
    member_id = serializers.UUIDField(required=False, help_text="Narrow the list to one organization membership id.")


class OrganizationMemberProjectAccessViewSetMixin(_GenericViewSet):
    @validated_request(
        query_serializer=MemberProjectAccessQuerySerializer,
        description="Every visible member's access to every project the caller can reach, with the rule behind it.",
        responses={200: OpenApiResponse(response=MemberProjectAccessResponseSerializer)},
        extensions={"x-product": "access_control"},
    )
    @action(methods=["GET"], detail=False, url_path="project_access", required_scopes=["organization_member:read"])
    def project_access(self, request: ValidatedRequest, *args: object, **kwargs: object) -> Response:
        organization = cast(Organization, self.organization)  # type: ignore[attr-defined]
        user = cast(User, request.user)
        requester = (
            OrganizationMembership.objects.filter(organization=organization, user=user)
            .select_related("organization")
            .first()
        )
        if requester is None:
            raise exceptions.NotFound()

        member_id = request.validated_query_data.get("member_id")
        results = member_project_access(organization, requester, user, member_id=member_id)
        if member_id is not None and not results:
            raise exceptions.NotFound()
        return Response(MemberProjectAccessResponseSerializer({"results": results}).data)
