from datetime import timedelta
from typing import Any, cast

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

import posthoganalytics
from drf_spectacular.utils import extend_schema
from loginas.utils import is_impersonated_session
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.admin.admins.data_deletion_request_admin import (
    _build_event_filter,
    _build_property_filter,
    _event_count_query_template,
)
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.data_deletion_request import DataDeletionRequest, RequestStatus, RequestType
from posthog.models.user import User
from posthog.permissions import TeamMemberStrictManagementPermission

PREVIEW_SAMPLE_LIMIT = 3000
FEATURE_FLAG_KEY = "data-deletion-self-serve"
# Only these request types are exposed in the self-serve UI. PERSON_REMOVAL is
# excluded because its Dagster job is not yet implemented.
SELF_SERVE_REQUEST_TYPES = {RequestType.EVENT_REMOVAL, RequestType.PROPERTY_REMOVAL}


def _user_can_self_serve(team) -> bool:
    return posthoganalytics.feature_enabled(
        FEATURE_FLAG_KEY,
        str(team.uuid),
        groups={"organization": str(team.organization_id)},
        group_properties={
            "organization": {
                "id": str(team.organization_id),
                "created_at": team.organization.created_at,
            }
        },
        send_feature_flag_events=False,
    )


class DataDeletionRequestSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = DataDeletionRequest
        fields = [
            "id",
            "request_type",
            "start_time",
            "end_time",
            "events",
            "delete_all_events",
            "hogql_predicate",
            "properties",
            "notes",
            "status",
            "approved",
            "approved_at",
            "execution_mode",
            "count",
            "min_timestamp",
            "max_timestamp",
            "stats_calculated_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "approved",
            "approved_at",
            "execution_mode",
            "count",
            "min_timestamp",
            "max_timestamp",
            "stats_calculated_at",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate_request_type(self, value: str) -> str:
        if value not in {rt.value for rt in SELF_SERVE_REQUEST_TYPES}:
            raise ValidationError(
                f"Only {sorted(rt.value for rt in SELF_SERVE_REQUEST_TYPES)} requests can be submitted self-serve."
            )
        return value

    def validate(self, attrs: dict) -> dict:
        request_type = attrs.get("request_type", getattr(self.instance, "request_type", None))
        properties = attrs.get("properties", [])
        if request_type == RequestType.PROPERTY_REMOVAL and not properties:
            raise ValidationError({"properties": "Property removal requests require at least one property."})
        if attrs.get("start_time") and attrs.get("end_time") and attrs["start_time"] >= attrs["end_time"]:
            raise ValidationError({"end_time": "end_time must be after start_time."})
        return super().validate(attrs)

    def create(self, validated_data: dict) -> DataDeletionRequest:
        team = self.context["get_team"]()
        request = self.context["request"]
        instance = DataDeletionRequest(
            team_id=team.id,
            created_by=request.user,
            created_by_staff=False,
            status=RequestStatus.PENDING,
            requires_approval=True,
            **validated_data,
        )
        # Re-use the model's full validation (HogQL compile, event/property sanity).
        try:
            instance.full_clean(exclude=["created_by"])
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)
        instance.save()
        return instance


class DataDeletionRequestPreviewInputSerializer(serializers.Serializer):
    request_type = serializers.ChoiceField(choices=[(rt.value, rt.value) for rt in SELF_SERVE_REQUEST_TYPES])
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    events = serializers.ListField(child=serializers.CharField(max_length=1024), required=False, default=list)
    delete_all_events = serializers.BooleanField(required=False, default=False)
    hogql_predicate = serializers.CharField(required=False, allow_blank=True, default="")
    properties = serializers.ListField(child=serializers.CharField(max_length=1024), required=False, default=list)

    def validate(self, attrs: dict) -> dict:
        if attrs["start_time"] >= attrs["end_time"]:
            raise ValidationError({"end_time": "end_time must be after start_time."})
        request_type = attrs["request_type"]
        if request_type == RequestType.EVENT_REMOVAL:
            if attrs["delete_all_events"] and attrs.get("events"):
                raise ValidationError({"events": "Events must be empty when delete_all_events is set."})
            has_event_scope = attrs["delete_all_events"] or bool(attrs.get("events"))
            has_predicate = bool(attrs.get("hogql_predicate", "").strip())
            if not has_event_scope and not has_predicate:
                raise ValidationError(
                    {"events": "Provide events, set delete_all_events, or add a HogQL predicate to scope the preview."}
                )
        elif request_type == RequestType.PROPERTY_REMOVAL:
            if not attrs.get("properties"):
                raise ValidationError({"properties": "Property removal requests require at least one property."})
            if attrs["delete_all_events"]:
                raise ValidationError({"delete_all_events": "delete_all_events is only valid for event_removal."})
        return attrs


def _run_preview(team_id: int, payload: dict) -> dict:
    """Run the count + sample queries for a deletion request preview.

    Uses an unsaved ``DataDeletionRequest`` so we can reuse the same HogQL/event/property
    filter helpers that the admin and Dagster pipeline use. Guarantees a single source of
    truth for the predicate — the customer-facing preview matches what would be deleted.
    """
    ephemeral = DataDeletionRequest(team_id=team_id, **payload)

    try:
        if payload["request_type"] == RequestType.PROPERTY_REMOVAL:
            extra_filter, params = _build_property_filter(ephemeral)
        else:
            extra_filter, params = _build_event_filter(ephemeral)
    except DjangoValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)

    with tags_context(
        product=Product.INTERNAL,
        feature=Feature.DATA_DELETION,
        team_id=team_id,
        workload=Workload.OFFLINE,
        query_type="self_serve_delete_preview_count",
    ):
        count_result = sync_execute(
            _event_count_query_template(extra_filter),
            params,
            team_id=team_id,
            readonly=True,
            workload=Workload.OFFLINE,
            ch_user=ClickHouseUser.META,
        )

    total = count_result[0][0] if count_result else 0
    min_ts = count_result[0][2] if count_result and total else None
    max_ts = count_result[0][3] if count_result and total else None

    sample_rows: list[dict[str, Any]] = []
    truncated = False
    if total:
        sample_sql = f"""
            SELECT
                uuid,
                event,
                timestamp,
                distinct_id,
                properties
            FROM events
            WHERE team_id = %(team_id)s
              AND timestamp >= %(start_time)s
              AND timestamp < %(end_time)s
              {extra_filter}
            ORDER BY timestamp DESC
            LIMIT {PREVIEW_SAMPLE_LIMIT + 1}
        """
        # Hard-coded LIMIT and column list prevent untrusted-parameter interpolation.
        with tags_context(
            product=Product.INTERNAL,
            feature=Feature.DATA_DELETION,
            team_id=team_id,
            workload=Workload.OFFLINE,
            query_type="self_serve_delete_preview_sample",
        ):
            raw_rows = sync_execute(
                sample_sql,
                params,
                team_id=team_id,
                readonly=True,
                workload=Workload.OFFLINE,
                ch_user=ClickHouseUser.META,
            )
        if len(raw_rows) > PREVIEW_SAMPLE_LIMIT:
            truncated = True
            raw_rows = raw_rows[:PREVIEW_SAMPLE_LIMIT]
        for row in raw_rows:
            sample_rows.append(
                {
                    "uuid": str(row[0]),
                    "event": row[1],
                    "timestamp": row[2].isoformat() if row[2] else None,
                    "distinct_id": row[3],
                    "properties": row[4],
                }
            )

    return {
        "count": total,
        "min_timestamp": min_ts.isoformat() if min_ts else None,
        "max_timestamp": max_ts.isoformat() if max_ts else None,
        "rows": sample_rows,
        "limit": PREVIEW_SAMPLE_LIMIT,
        "truncated": truncated,
    }


@extend_schema(tags=["data_deletion_requests"])
class DataDeletionRequestViewSet(
    TeamAndOrgViewSetMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "INTERNAL"
    queryset = DataDeletionRequest.objects.all().order_by("-created_at")
    serializer_class = DataDeletionRequestSerializer
    permission_classes = [TeamMemberStrictManagementPermission]

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id, request_type__in=[rt.value for rt in SELF_SERVE_REQUEST_TYPES])

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if not _user_can_self_serve(self.team):
            # 404 (not 403) so teams without the flag can't infer the endpoint exists.
            raise NotFound()

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        instance = serializer.save()
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=cast(User, self.request.user),
            was_impersonated=is_impersonated_session(self.request),
            scope="DataManagement",
            item_id=instance.pk,
            activity="created",
            detail=Detail(name=f"{instance.request_type} request"),
        )

    def perform_destroy(self, instance: DataDeletionRequest) -> None:
        if instance.status != RequestStatus.PENDING:
            raise PermissionDenied(
                "Only pending requests can be cancelled. Contact PostHog support to cancel an approved request."
            )
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=cast(User, self.request.user),
            was_impersonated=is_impersonated_session(self.request),
            scope="DataManagement",
            item_id=instance.pk,
            activity="deleted",
            detail=Detail(name=f"{instance.request_type} request"),
        )
        instance.delete()

    @extend_schema(
        request=DataDeletionRequestPreviewInputSerializer,
        responses={200: None},
    )
    @action(methods=["POST"], detail=False)
    def preview(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Preview the rows a hypothetical deletion request would match."""
        input_serializer = DataDeletionRequestPreviewInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        payload = dict(input_serializer.validated_data)
        # Bound the time range to avoid preview queries scanning the entire events table
        # when the user starts typing but hasn't picked a date yet.
        if payload["end_time"] > timezone.now() + timedelta(days=1):
            raise ValidationError({"end_time": "end_time cannot be more than a day in the future."})
        result = _run_preview(self.team_id, payload)
        return Response(result, status=status.HTTP_200_OK)
