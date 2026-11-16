from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_serializer
from rest_framework import exceptions, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models.event.new_events_schema import (
    project_can_opt_in_to_new_events_table,
    project_moved_to_new_events_table,
    project_opted_in_to_new_events_table,
    project_reads_new_events_table,
    set_project_events_table_opt_in,
)
from posthog.models.user import User
from posthog.permissions import OrganizationAdminWritePermissions


@extend_schema_serializer(many=False)
class EventsTableSerializer(serializers.Serializer):
    use_new_events_table = serializers.BooleanField(
        read_only=True,
        help_text="Whether this project opted in to the new events table before PostHog moves it there.",
    )
    reads_new_events_table = serializers.BooleanField(
        read_only=True,
        help_text="Whether this project's queries read the new events table now, because it opted in or because PostHog moved it.",
    )
    can_choose = serializers.BooleanField(
        read_only=True,
        help_text="Whether this project can opt in or undo its opt-in. False once PostHog has moved the project, which can't be undone, and while opting in is not open yet. While false, a save is refused.",
    )


class EventsTableUpdateSerializer(serializers.Serializer):
    use_new_events_table = serializers.BooleanField(
        help_text="True to move this project to the new events table before PostHog moves it. False to undo that. A change reaches every query within about a minute.",
    )


@extend_schema(tags=["events_table"], extensions={"x-product": ProductKey.PRODUCT_ANALYTICS})
class EventsTableViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "project"
    pagination_class = None
    permission_classes = [OrganizationAdminWritePermissions]

    def _can_choose(self) -> bool:
        return project_can_opt_in_to_new_events_table(self.team_id) and not project_moved_to_new_events_table(
            self.team_id
        )

    def _events_table_response(self) -> Response:
        return Response(
            EventsTableSerializer(
                {
                    "use_new_events_table": project_opted_in_to_new_events_table(self.team_id),
                    "reads_new_events_table": project_reads_new_events_table(self.team_id),
                    "can_choose": self._can_choose(),
                }
            ).data
        )

    @extend_schema(
        operation_id="events_table_retrieve",
        summary="Get the events table a project reads",
        description=(
            "Returns which events table this project's queries read, whether the project opted in early, and "
            "whether it can still choose."
        ),
        responses={200: EventsTableSerializer},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._events_table_response()

    @validated_request(
        EventsTableUpdateSerializer,
        operation_id="events_table_update",
        summary="Choose the events table a project reads",
        description=(
            "Moves this project's queries to the new events table before PostHog moves it, or undoes that. Once "
            "PostHog has moved the project, it can't switch back. The switch deletes nothing. Organization admins "
            "only."
        ),
        responses={
            200: OpenApiResponse(response=EventsTableSerializer, description="The project's new choice."),
            403: OpenApiResponse(
                description="The user isn't an organization admin, PostHog already moved the project, or opting in isn't open yet."
            ),
        },
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        if project_moved_to_new_events_table(self.team_id):
            raise exceptions.PermissionDenied(
                "PostHog moved this project to the new events table. It can't switch back."
            )
        if not project_can_opt_in_to_new_events_table(self.team_id):
            raise exceptions.PermissionDenied("This project can't switch its events table yet.")

        use_new_events_table = request.validated_data["use_new_events_table"]
        set_project_events_table_opt_in(self.team_id, use_new_events_table)
        report_user_action(
            cast(User, request.user),
            "events table choice changed",
            {"use_new_events_table": use_new_events_table},
            team=self.team,
            request=request,
        )
        return self._events_table_response()
