from typing import Any, cast

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import User

from products.conversations.backend.models import AgentOutOfOffice


class AgentOutOfOfficeSerializer(serializers.ModelSerializer):
    user = UserBasicSerializer(read_only=True, help_text="The agent who is out of office.")
    since = serializers.DateTimeField(
        source="created_at", read_only=True, help_text="When the agent set themselves out of office."
    )

    class Meta:
        model = AgentOutOfOffice
        fields = ["id", "user", "since"]
        read_only_fields = ["id", "user", "since"]
        extra_kwargs = {"id": {"help_text": "UUID of the out-of-office entry."}}


@extend_schema_view(list=extend_schema(operation_id="conversations_out_of_office_list"))
class AgentOutOfOfficeViewSet(TeamAndOrgViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    # "ticket" (not "conversation"), as for macros: the conversation scope also authorizes AI
    # conversation endpoints.
    scope_object = "ticket"
    queryset = AgentOutOfOffice.objects.unscoped()
    serializer_class = AgentOutOfOfficeSerializer

    @property
    def requires_resource_level_access(self) -> bool:
        # The entry is not a ticket object, so an editor grant on one ticket must not unlock it.
        return self.action == "me"

    def safely_get_queryset(self, queryset: Any) -> Any:
        return queryset.filter(team_id=self.team_id).select_related("user").order_by("created_at", "id")

    @extend_schema(
        methods=["POST"],
        request=None,
        responses={status.HTTP_200_OK: AgentOutOfOfficeSerializer, status.HTTP_201_CREATED: AgentOutOfOfficeSerializer},
        operation_id="conversations_out_of_office_me_create",
        description="Set yourself out of office. Calling it again while you are away keeps the original time.",
    )
    @extend_schema(
        methods=["DELETE"],
        request=None,
        responses={status.HTTP_204_NO_CONTENT: None},
        operation_id="conversations_out_of_office_me_destroy",
        description="Clear your own out-of-office status. Succeeds when you were not away.",
    )
    @action(detail=False, methods=["post", "delete"], url_path="me", required_scopes=["ticket:write"])
    def me(self, request: Request, **kwargs: Any) -> Response:
        user = cast(User, request.user)
        entries = AgentOutOfOffice.objects.for_team(self.team_id)
        if request.method == "DELETE":
            current = entries.filter(user=user).first()
            if current is not None:
                # Instance delete, not a queryset one, so the activity log records it.
                current.delete()
                report_user_action(user, "support out of office cleared", team=self.team, request=request)
            return Response(status=status.HTTP_204_NO_CONTENT)

        entry, created = entries.get_or_create(team_id=self.team_id, user=user)
        if created:
            report_user_action(user, "support out of office set", team=self.team, request=request)
        return Response(
            self.get_serializer(entry).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )
