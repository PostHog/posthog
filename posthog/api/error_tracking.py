from uuid import UUID

from django.db.models import QuerySet
from loginas.utils import is_impersonated_session
from rest_framework import serializers, viewsets, status, request

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.activity_logging.activity_log import log_activity, Detail, Change, load_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.error_tracking import ErrorTrackingGroup
from posthog.api.utils import action
from rest_framework.response import Response
from django.utils.http import urlsafe_base64_decode
import json


class ErrorTrackingGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingGroup
        fields = ["assignee", "status"]


class ErrorTrackingGroupViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingGroup.objects.all()
    serializer_class = ErrorTrackingGroupSerializer

    def safely_get_object(self, queryset) -> QuerySet:
        stringified_fingerprint = self.kwargs["pk"]
        fingerprint = json.loads(urlsafe_base64_decode(stringified_fingerprint))
        group, _ = queryset.get_or_create(fingerprint=fingerprint, team=self.team)
        return group

    @action(methods=["POST"], detail=True)
    def merge(self, request, **kwargs):
        group: ErrorTrackingGroup = self.get_object()
        before = group.merged_fingerprints

        merging_fingerprints: list[list[str]] = request.data.get("merging_fingerprints", [])
        group.merge(merging_fingerprints)

        log_activity(
            # FIXME: i assume this is some mypy confusion that doesn't know a UUIDField is a UUID
            organization_id=UUID(str(self.organization_id)),
            team_id=self.team_id,
            user=request.user,
            was_impersonated=is_impersonated_session(request),
            scope="ErrorTrackingGroup",
            item_id=str(group.id),
            activity="merged_fingerprints",
            detail=Detail(
                changes=[
                    Change(
                        type="ErrorTrackingGroup",
                        field="merged_fingerprints",
                        before=before,
                        after=merging_fingerprints,
                        action="merged",
                    )
                ]
            ),
        )

        return Response({"success": True})

    @action(methods=["GET"], url_path="activity", detail=False, required_scopes=["activity_log:read"])
    def all_activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="ErrorTrackingGroup", team_id=self.team_id, limit=limit, page=page)
        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["GET"], detail=True, required_scopes=["activity_log:read"])
    def activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        item_id = kwargs["pk"]
        if not ErrorTrackingGroup.objects.filter(id=item_id, team_id=self.team_id).exists():
            return Response("", status=status.HTTP_404_NOT_FOUND)

        activity_page = load_activity(
            scope="ErrorTrackingGroup",
            team_id=self.team_id,
            item_ids=[str(item_id)],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)
