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
    project_can_choose_events_table,
    project_events_table_choice,
    project_reads_new_events_table,
    set_project_events_table_choice,
)
from posthog.models.user import User
from posthog.permissions import OrganizationAdminWritePermissions


@extend_schema_serializer(many=False)
class EventsTableSerializer(serializers.Serializer):
    use_new_events_table = serializers.BooleanField(
        read_only=True,
        allow_null=True,
        help_text="The events table this project chose: true for the new table, false for the old table, null while the project has made no choice.",
    )
    reads_new_events_table = serializers.BooleanField(
        read_only=True,
        help_text="Whether this project's queries read the new events table now, by its own choice or because PostHog moved it.",
    )
    can_choose = serializers.BooleanField(
        read_only=True,
        help_text="Whether this project can choose its events table. While false, a save is refused.",
    )


class EventsTableUpdateSerializer(serializers.Serializer):
    use_new_events_table = serializers.BooleanField(
        allow_null=True,
        help_text="True to read the new events table, false to read the old table, null to drop the project's choice and follow PostHog's rollout. A change reaches every query within about a minute.",
    )


@extend_schema(tags=["events_table"], extensions={"x-product": ProductKey.PRODUCT_ANALYTICS})
class EventsTableViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "project"
    pagination_class = None
    permission_classes = [OrganizationAdminWritePermissions]

    def _events_table_response(self) -> Response:
        return Response(
            EventsTableSerializer(
                {
                    "use_new_events_table": project_events_table_choice(self.team_id),
                    "reads_new_events_table": project_reads_new_events_table(self.team_id),
                    "can_choose": project_can_choose_events_table(self.team_id),
                }
            ).data
        )

    @extend_schema(
        operation_id="events_table_retrieve",
        summary="Get the events table a project reads",
        description=(
            "Returns which events table this project's queries read, the choice the project made for itself, and "
            "whether the project can choose yet."
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
            "Switches this project's queries to the new events table or back to the old one. The switch deletes "
            "nothing and can be reversed. Batch exports are not affected. Organization admins only."
        ),
        responses={
            200: OpenApiResponse(response=EventsTableSerializer, description="The project's new choice."),
            403: OpenApiResponse(
                description="The user isn't an organization admin, or the project can't choose its events table yet."
            ),
        },
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        if not project_can_choose_events_table(self.team_id):
            raise exceptions.PermissionDenied("This project can't choose its events table yet.")

        use_new_events_table = request.validated_data["use_new_events_table"]
        set_project_events_table_choice(self.team, use_new_events_table)
        report_user_action(
            cast(User, request.user),
            "events table choice changed",
            {"use_new_events_table": use_new_events_table},
            team=self.team,
            request=request,
        )
        return self._events_table_response()
