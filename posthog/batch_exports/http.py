import datetime as dt
from typing import Any

from django.utils.timezone import now
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated, NotFound, ValidationError
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.batch_exports.service import (
    BatchExportIdError,
    BatchExportServiceError,
    BatchExportServiceRPCError,
    backfill_export,
    create_batch_export,
    delete_schedule,
    pause_batch_export,
    reset_batch_export_run,
    unpause_batch_export,
    update_batch_export,
)
from posthog.models import BatchExport, BatchExportDestination, BatchExportRun, User
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.temporal.client import sync_connect
from posthog.utils import relative_date_parse, relative_date_parse_with_delta_mapping


def validate_date_input(date_input: Any) -> dt.datetime:
    """Parse any datetime input as a proper dt.datetime.

    Args:
        date_input: The datetime input to parse.

    Raises:
        ValidationError: If the input cannot be parsed.

    Returns:
        The parsed dt.datetime.
    """
    try:
        # The Right Way (TM) to check this would be by calling isinstance, but that doesn't feel very Pythonic.
        # As far as I'm concerned, if you give me something that quacks like an isoformatted str, you are golden.
        # Read more here: https://github.com/python/mypy/issues/2420.
        # Once PostHog is 3.11, try/except is zero cost if nothing is raised: https://bugs.python.org/issue40222.
        parsed = dt.datetime.fromisoformat(date_input.replace("Z", "+00:00"))  # type: ignore
    except (TypeError, ValueError):
        raise ValidationError(f"Input {date_input} is not a valid ISO formatted datetime.")
    return parsed


class BatchExportRunSerializer(serializers.ModelSerializer):
    """Serializer for a BatchExportRun model."""

    class Meta:
        model = BatchExportRun
        fields = "__all__"
        # TODO: Why aren't all these read only?
        read_only_fields = ["batch_export"]


class RunsCursorPagination(CursorPagination):
    ordering = "-created_at"
    page_size = 100


class BatchExportRunViewSet(StructuredViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = BatchExportRun.objects.all()
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    serializer_class = BatchExportRunSerializer
    pagination_class = RunsCursorPagination

    def get_queryset(self, date_range: tuple[dt.datetime, dt.datetime] | None = None):
        if not isinstance(self.request.user, User) or self.request.user.current_team is None:
            raise NotAuthenticated()

        if date_range:
            return self.queryset.filter(
                batch_export_id=self.kwargs["parent_lookup_batch_export_id"], created_at__range=date_range
            ).order_by("-created_at")
        else:
            return self.queryset.filter(batch_export_id=self.kwargs["parent_lookup_batch_export_id"]).order_by(
                "-created_at"
            )

    def list(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Get all BatchExportRuns for a BatchExport."""
        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        after = self.request.query_params.get("after", "-7d")
        before = self.request.query_params.get("before", None)
        after_datetime = relative_date_parse(after)
        before_datetime = relative_date_parse(before) if before else now()
        date_range = (after_datetime, before_datetime)

        page = self.paginate_queryset(self.get_queryset(date_range=date_range))
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(methods=["POST"], detail=True)
    def reset(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Reset a BatchExportRun by resetting its associated Temporal Workflow."""
        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        batch_export_run = self.get_object()
        temporal = sync_connect()

        scheduled_id = f"{batch_export_run.batch_export.id}-{batch_export_run.data_interval_end:%Y-%m-%dT%H:%M:%SZ}"
        new_run_id = reset_batch_export_run(temporal, batch_export_id=scheduled_id)

        return response.Response({"new_run_id": new_run_id})


class BatchExportDestinationSerializer(serializers.ModelSerializer):
    """Serializer for an BatchExportDestination model."""

    class Meta:
        model = BatchExportDestination
        fields = ["type", "config"]

    def create(self, validated_data: dict) -> BatchExportDestination:
        """Create a BatchExportDestination."""
        export_destination = BatchExportDestination.objects.create(**validated_data)
        return export_destination

    def to_representation(self, instance: BatchExportDestination) -> dict:
        data = super().to_representation(instance)
        data["config"] = {
            k: v for k, v in data["config"].items() if k not in BatchExportDestination.secret_fields[instance.type]
        }
        return data


class BatchExportSerializer(serializers.ModelSerializer):
    """Serializer for a BatchExport model."""

    destination = BatchExportDestinationSerializer()
    latest_runs = BatchExportRunSerializer(many=True, read_only=True)
    trigger_immediately = serializers.BooleanField(default=False)

    class Meta:
        model = BatchExport
        fields = [
            "id",
            "name",
            "destination",
            "interval",
            "paused",
            "created_at",
            "last_updated_at",
            "last_paused_at",
            "start_at",
            "end_at",
            "trigger_immediately",
            "latest_runs",
        ]
        read_only_fields = ["id", "paused", "created_at", "last_updated_at", "latest_runs"]

    def create(self, validated_data: dict) -> BatchExport:
        """Create a BatchExport."""
        destination_data = validated_data.pop("destination")
        team_id = self.context["team_id"]
        interval = validated_data.pop("interval")
        name = validated_data.pop("name")
        start_at = validated_data.get("start_at", None)
        end_at = validated_data.get("end_at", None)
        trigger_immediately = validated_data.get("trigger_immediately", False)

        return create_batch_export(
            team_id=team_id,
            interval=interval,
            name=name,
            destination_data=destination_data,
            start_at=start_at,
            end_at=end_at,
            trigger_immediately=trigger_immediately,
        )

    def update(self, instance: BatchExport, validated_data: dict) -> BatchExport:
        """Update a BatchExport."""
        destination_data = validated_data.pop("destination", None)
        interval = validated_data.get("interval", None)
        name = validated_data.get("name", None)
        start_at = validated_data.get("start_at", None)
        end_at = validated_data.get("end_at", None)

        return update_batch_export(
            batch_export=instance,
            interval=interval,
            name=name,
            destination_data=destination_data,
            start_at=start_at,
            end_at=end_at,
        )


class BatchExportViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = BatchExport.objects.all()
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    serializer_class = BatchExportSerializer

    def get_queryset(self):
        if not isinstance(self.request.user, User) or self.request.user.current_team is None:
            raise NotAuthenticated()

        return (
            self.queryset.filter(team_id=self.team_id)
            .exclude(deleted=True)
            .order_by("-created_at")
            .prefetch_related("destination")
        )

    @action(methods=["POST"], detail=True)
    def backfill(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Trigger a backfill for a BatchExport."""
        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        start_at_input = request.data.get("start_at", None)
        end_at_input = request.data.get("end_at", None)

        if start_at_input is None or end_at_input is None:
            raise ValidationError("Both 'start_at' and 'end_at' must be specified")

        start_at = validate_date_input(start_at_input)
        end_at = validate_date_input(end_at_input)

        if start_at >= end_at:
            raise ValidationError("The initial backfill datetime 'start_at' happens after 'end_at'")

        batch_export = self.get_object()
        temporal = sync_connect()
        backfill_export(temporal, str(batch_export.pk), start_at, end_at)

        return response.Response()

    @action(methods=["POST"], detail=True)
    def pause(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Pause a BatchExport."""
        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        user_id = request.user.distinct_id
        team_id = request.user.current_team.id
        note = f"Pause requested by user {user_id} from team {team_id}"

        batch_export = self.get_object()
        temporal = sync_connect()

        try:
            pause_batch_export(temporal, str(batch_export.id), note=note)
        except BatchExportIdError:
            raise NotFound(f"BatchExport ID '{str(batch_export.id)}' not found.")
        except BatchExportServiceRPCError:
            raise ValidationError("Invalid request to pause a BatchExport could not be carried out")
        except BatchExportServiceError:
            raise

        return response.Response({"paused": True})

    @action(methods=["POST"], detail=True)
    def unpause(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Unpause a BatchExport."""
        if not isinstance(request.user, User) or request.user.current_team is None:
            raise NotAuthenticated()

        user_id = request.user.distinct_id
        team_id = request.user.current_team.id
        note = f"Unpause requested by user {user_id} from team {team_id}"
        backfill = request.data.get("backfill", False)

        batch_export = self.get_object()
        temporal = sync_connect()

        try:
            unpause_batch_export(temporal, str(batch_export.id), note=note, backfill=backfill)
        except BatchExportIdError:
            raise NotFound(f"BatchExport ID '{str(batch_export.id)}' not found.")
        except BatchExportServiceRPCError:
            raise ValidationError("Invalid request to unpause a BatchExport could not be carried out")
        except BatchExportServiceError:
            raise

        return response.Response({"paused": False})

    def perform_destroy(self, instance: BatchExport):
        """Perform a BatchExport destroy by clearing Temporal and Django state."""
        instance.deleted = True
        temporal = sync_connect()
        delete_schedule(temporal, str(instance.pk))
        instance.save()
