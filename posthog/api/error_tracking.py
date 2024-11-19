from rest_framework import serializers, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import QuerySet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.error_tracking.error_tracking import ErrorTrackingSymbolSet, ErrorTrackingStackFrame


class ErrorTrackingStackFrameSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingStackFrame
        fields = ["id", "raw_id", "created_at", "contents", "resolved", "context"]


class ErrorTrackingSymbolSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingSymbolSet
        fields = ["id", "ref", "team_id", "created_at", "storage_ptr", "failure_reason"]
        read_only_fields = ["team_id"]


class ErrorTrackingSymbolSetViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "query"
    serializer_class = ErrorTrackingSymbolSetSerializer
    queryset = ErrorTrackingSymbolSet.objects.all()

    scope_object_read_actions = ["list", "retrieve", "stack_frames"]  # Add this line

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team.id)

    @action(methods=["GET"], detail=True)
    def stack_frames(self, request, *args, **kwargs):
        symbol_set = self.get_object()
        frames = ErrorTrackingStackFrame.objects.filter(symbol_set=symbol_set, team_id=self.team.id)
        serializer = ErrorTrackingStackFrameSerializer(frames, many=True)
        return Response(serializer.data)

    def perform_destroy(self, instance):
        # The related stack frames will be deleted via CASCADE
        instance.delete()
