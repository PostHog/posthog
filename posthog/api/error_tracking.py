from typing import Any

from rest_framework import request, serializers, viewsets
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
            "id",
            "created_at",
            "status",
            "fingerprint",
            "merged_fingerprints",
            "assignee",
        ]


class ErrorTrackingGroupViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    serializer_class = ErrorTrackingGroupSerializer

    @action(methods=["GET"], detail=False)
    def merge(self, request: request.Request, **kwargs):

        return Response([])


class ErrorTrackingGroupViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    serializer_class = ErrorTrackingGroupSerializer
    queryset = ErrorTrackingGroup.objects.all()

    def safely_get_queryset(self, queryset) -> QuerySet:
        queryset = queryset.select_related("assignee").filter(team=self.team)

        if self.action == "list":
            queryset = queryset.filter(
                status=[ErrorTrackingGroup.Status.ACTIVE, ErrorTrackingGroup.Status.PENDING_RELEASE]
            )
            queryset = self._filter_list_request(self.request, queryset)
        elif self.action == "retreive":
            fingerprint = request.GET.get("fingerprint")

            queryset = queryset.filter(
                Q(fingerprint__in=[fingerprint]) | Q(merged_fingerprints__contains=[fingerprint])
            )

        return queryset

    # def list(self, request: Request):
    #     pass

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        serializer = self.get_serializer(instance)

        if str(request.headers.get("If-None-Match")) == str(instance.version):
            return Response(None, 304)

        return Response(serializer.data)

    @action(methods=["POST"], url_path="merge", detail=False)
    def merge(self, request: Request, **kwargs):

        return Response([])
        # limit = int(request.query_params.get("limit", "10"))
        # page = int(request.query_params.get("page", "1"))

        # activity_page = load_activity(scope="Notebook", team_id=self.team_id, limit=limit, page=page)
        # return activity_page_response(activity_page, limit, page, request)
