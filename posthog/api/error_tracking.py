from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.error_tracking import ErrorTrackingGroup
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from django.db.models import QuerySet
from rest_framework.request import Request
from django.db.models import Q


class ErrorTrackingGroupSerializer(serializers.ModelSerializer):
    assignee = UserBasicSerializer(read_only=True)

    class Meta:
        model = ErrorTrackingGroup
        fields = [
            "status",
            "fingerprint",
            "merged_fingerprints",
            "assignee",
        ]


class ErrorTrackingGroupViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    # TODO: we will probably want this accessible via the API at some point
    scope_object = "INTERNAL"
    serializer_class = ErrorTrackingGroupSerializer
    queryset = ErrorTrackingGroup.objects.all()

    def safely_get_queryset(self, queryset) -> QuerySet:
        params = self.request.GET
        fingerprints = (
            [params.get("fingerprint", "")] if self.action == "retrieve" else params.getlist("fingerprints", [])
        )

        queryset = (
            queryset.select_related("assignee").filter(team=self.team).filter(self._fingerprints_filter(fingerprints))
        )

        return queryset

    @action(methods=["POST"], url_path="merge", detail=True)
    def merge(self, request: Request, **kwargs):
        group: ErrorTrackingGroup = self.get_object()

        merge_groups = ErrorTrackingGroup.objects.filter(
            team=self.team,
        ).filter(self._fingerprints_filter)

        group.merge(groups=list(merge_groups))

        return Response([])

    def _fingerprints_filter(self, fingerprints):
        query = Q(fingerprint__in=fingerprints)

        for fp in fingerprints:
            query |= Q(merged_fingerprints__contains=[fp])

        return query
