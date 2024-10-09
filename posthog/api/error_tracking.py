import json
from uuid import UUID

import structlog
from django.conf import settings
from django.db.models import QuerySet
from django.utils.http import urlsafe_base64_decode
from loginas.utils import is_impersonated_session
from rest_framework import serializers, viewsets, status, request
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.models.activity_logging.activity_log import log_activity, Detail, Change, load_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.error_tracking import ErrorTrackingGroup
from posthog.storage import object_storage

FIFTY_MEGABYTES = 50 * 1024 * 1024

logger = structlog.get_logger(__name__)


class ObjectStorageUnavailable(Exception):
    pass


class ErrorTrackingGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingGroup
        fields = ["assignee", "status"]

    def update(self, instance, validated_data):
        status_updated = "status" in validated_data and validated_data.get("status") != instance.status
        status_before = instance.status
        assignee_updated = "assignee" in validated_data and validated_data.get("assignee") != instance.assignee
        assignee_before = instance.assignee

        updated_instance = super().update(instance, validated_data)

        if status_updated or assignee_updated:
            changes: list[Change] = []
            if status_updated:
                changes.append(
                    Change(
                        type="ErrorTrackingGroup",
                        field="status",
                        before=status_before,
                        after=validated_data.get("status"),
                        action="changed",
                    )
                )

            if assignee_updated:
                serialized_before = UserBasicSerializer(assignee_before).data
                serialized_after = UserBasicSerializer(validated_data.get("assignee")).data
                changes.append(
                    Change(
                        type="ErrorTrackingGroup",
                        field="assignee",
                        before=serialized_before,
                        after=serialized_after,
                        action="changed",
                    )
                )

            organization = self.context["get_organization"]()

            log_activity(
                organization_id=organization.id,
                team_id=self.context["team_id"],
                user=self.context["request"].user,
                was_impersonated=is_impersonated_session(self.context["request"]),
                item_id=str(updated_instance.id),
                scope="ErrorTrackingGroup",
                activity="updated",
                detail=Detail(
                    changes=changes,
                ),
            )

        return updated_instance


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

    @action(methods=["POST"], detail=False)
    def upload_source_maps(self, request, **kwargs):
        try:
            if settings.OBJECT_STORAGE_ENABLED:
                file = request.FILES["source_map"]
                if file.size > FIFTY_MEGABYTES:
                    raise ValidationError(code="file_too_large", detail="Source maps must be less than 50MB")

                upload_path = (
                    f"{settings.OBJECT_STORAGE_ERROR_TRACKING_SOURCE_MAPS_FOLDER}/team-{self.team_id}/{file.name}"
                )

                object_storage.write(upload_path, file)
                return Response({"ok": True}, status=status.HTTP_201_CREATED)
            else:
                raise ObjectStorageUnavailable()
        except ObjectStorageUnavailable:
            raise ValidationError(
                code="object_storage_required",
                detail="Object storage must be available to allow source map uploads.",
            )
