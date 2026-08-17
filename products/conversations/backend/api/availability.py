"""Reading and changing whether agents are taking tickets.

Organization-nested rather than project-nested: assignees are validated against organization
membership, so availability applies to every project in the org.
"""

from typing import cast

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import OrganizationMembership
from posthog.models.user import User

from products.conversations.backend.models import AgentAvailability
from products.conversations.backend.services.availability import set_availability


class AgentAvailabilitySerializer(serializers.ModelSerializer):
    """One agent's availability for support tickets."""

    user = UserBasicSerializer(read_only=True, help_text="The agent this availability belongs to.")
    is_available = serializers.BooleanField(read_only=True, help_text="Whether the agent is currently taking tickets.")
    changed_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text=(
            "Who last changed it: the agent themselves, or an organization admin. "
            "Null when a workflow or API token changed it, or if that account has since been deleted."
        ),
    )
    updated_at = serializers.DateTimeField(read_only=True, help_text="When it last changed.")

    class Meta:
        model = AgentAvailability
        fields = ["user", "is_available", "changed_by", "updated_at"]
        read_only_fields = fields


class SetAgentAvailabilitySerializer(serializers.Serializer):
    """Payload for changing one agent's availability."""

    is_available = serializers.BooleanField(
        help_text=(
            "False stops new tickets being assigned to this agent. True makes them assignable "
            "again. Tickets they already hold are left alone either way."
        ),
    )


class AgentAvailabilityStateSerializer(serializers.Serializer):
    """One agent's availability after a change."""

    user_id = serializers.IntegerField(read_only=True, help_text="The agent this state belongs to.")
    is_available = serializers.BooleanField(read_only=True, help_text="Whether the agent is now taking tickets.")


class AgentAvailabilityViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "ticket"
    scope_object_read_actions = ["list"]
    scope_object_write_actions = ["update"]
    serializer_class = AgentAvailabilitySerializer
    queryset = AgentAvailability.objects.all()
    # Rows only exist for agents whose availability has been set, which stays small next to the
    # organization's member list.
    pagination_class = None
    # Addressed by the agent's user id, not the availability row's own UUID: callers know who they
    # mean, and a row only exists once someone's availability has been set.
    lookup_value_regex = r"[0-9]+"

    def safely_get_queryset(self, queryset):
        return queryset.filter(organization=self.organization).select_related("user", "changed_by")

    @extend_schema(responses={200: AgentAvailabilitySerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        entries = self.get_queryset().order_by("user_id")
        return Response(AgentAvailabilitySerializer(entries, many=True).data)

    # PUT rather than PATCH: the body fully describes the state, so there's no partial version of
    # this request to express.
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="id",
                type=int,
                location=OpenApiParameter.PATH,
                description="Numeric user id of the agent whose availability is being set.",
            )
        ],
        request=SetAgentAvailabilitySerializer,
        responses={200: AgentAvailabilityStateSerializer},
    )
    def update(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        target_user_id = self._parse_target_user_id(pk)
        actor = cast(User, request.user)
        self._check_can_set_for(target_user_id, actor)

        serializer = SetAgentAvailabilitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        is_available = serializer.validated_data["is_available"]

        changed = set_availability(
            organization=self.organization,
            target_user_id=target_user_id,
            actor=actor,
            is_available=is_available,
        )
        if changed:
            report_user_action(
                actor,
                "support agent availability changed",
                {"is_available": is_available, "is_self": actor.id == target_user_id},
                organization=self.organization,
                request=request,
            )

        return Response(
            AgentAvailabilityStateSerializer({"user_id": target_user_id, "is_available": is_available}).data
        )

    def _parse_target_user_id(self, pk: str | None) -> int:
        try:
            target_user_id = int(pk or "")
        except ValueError:
            raise exceptions.NotFound("Person not found.")
        # Python ints are unbounded but the column is a bigint, so an oversized id would reach
        # Postgres and raise DataError instead of answering "no such person".
        if not -(2**63) <= target_user_id < 2**63:
            raise exceptions.NotFound("Person not found.")

        if not OrganizationMembership.objects.filter(organization=self.organization, user_id=target_user_id).exists():
            raise exceptions.NotFound("Person not found.")
        return target_user_id

    def _check_can_set_for(self, target_user_id: int, actor: User) -> None:
        if actor.id == target_user_id:
            return

        membership = OrganizationMembership.objects.filter(organization=self.organization, user=actor).first()
        if membership is None or membership.level < OrganizationMembership.Level.ADMIN:
            raise exceptions.PermissionDenied(
                "You can only change your own availability. Ask an organization admin to change someone else's."
            )
