import json
from typing import Any, List, Type, cast

from dateutil import parser
import requests
from django.db.models import Count, Prefetch
from django.http import JsonResponse, HttpResponse
from loginas.utils import is_impersonated_session
from rest_framework import exceptions, request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from sentry_sdk import capture_exception

from posthog.api.person import PersonSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.auth import SharingAccessTokenAuthentication
from posthog.constants import SESSION_RECORDINGS_FILTER_IDS
from posthog.models import Filter
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.person.person import PersonDistinctId
from posthog.models.session_recording.session_recording import SessionRecording
from posthog.models.session_recording_event import SessionRecordingViewed
from posthog.permissions import (
    ProjectMembershipNecessaryPermissions,
    SharingTokenPermission,
    TeamMemberAccessPermission,
)
from posthog.queries.session_recordings.session_recording_list import SessionRecordingList, SessionRecordingListV2
from posthog.queries.session_recordings.session_recording_list_from_replay_summary import (
    SessionRecordingListFromReplaySummary,
)
from posthog.queries.session_recordings.session_recording_properties import SessionRecordingProperties
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.storage import object_storage
from posthog.utils import format_query_params_absolute_url

DEFAULT_RECORDING_CHUNK_LIMIT = 20  # Should be tuned to find the best value


class SessionRecordingSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source="session_id", read_only=True)
    recording_duration = serializers.IntegerField(source="duration", read_only=True)
    person = PersonSerializer(required=False)

    class Meta:
        model = SessionRecording
        fields = [
            "id",
            "distinct_id",
            "viewed",
            "recording_duration",
            "start_time",
            "end_time",
            "click_count",
            "keypress_count",
            "start_url",
            "matching_events",
            "person",
            "storage",
            "pinned_count",
        ]

        read_only_fields = [
            "id",
            "distinct_id",
            "viewed",
            "recording_duration",
            "start_time",
            "end_time",
            "click_count",
            "keypress_count",
            "start_url",
            "matching_events",
            "storage",
            "pinned_count",
        ]


class SessionRecordingSharedSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source="session_id", read_only=True)
    recording_duration = serializers.IntegerField(source="duration", read_only=True)

    class Meta:
        model = SessionRecording
        fields = ["id", "recording_duration", "start_time", "end_time"]


class SessionRecordingPropertiesSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    properties = serializers.DictField(required=False)

    def to_representation(self, instance):
        return {
            "id": instance["session_id"],
            "properties": instance["properties"],
        }


class SessionRecordingViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    authentication_classes = StructuredViewSetMixin.authentication_classes + [SharingAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = SessionRecordingSerializer

    sharing_enabled_actions = ["retrieve", "snapshots", "snapshot_file"]

    def get_permissions(self):
        if hasattr(self.request, "sharing_configuration"):
            return [permission() for permission in [SharingTokenPermission]]
        return super().get_permissions()

    def get_serializer_class(self) -> Type[serializers.Serializer]:
        if hasattr(self.request, "sharing_configuration"):
            return SessionRecordingSharedSerializer
        else:
            return SessionRecordingSerializer

    def get_object(self):
        team = self.team
        session_id = self.kwargs["pk"]
        obj = SessionRecording.get_or_build(session_id=session_id, team=team)
        self.check_object_permissions(self.request, obj)
        return obj

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        filter = SessionRecordingsFilter(request=request, team=self.team)
        use_v2_list = request.GET.get("version") == "2"
        use_v3_list = request.GET.get("version") == "3"

        return Response(
            list_recordings(filter, request, context=self.get_serializer_context(), v2=use_v2_list, v3=use_v3_list)
        )

    # Returns metadata about the recording
    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        recording = self.get_object()

        if recording.deleted:
            raise exceptions.NotFound("Recording not found")

        # Optimisation step if passed to speed up retrieval of CH data
        if not recording.start_time:
            recording_start_time = (
                parser.parse(request.GET["recording_start_time"]) if request.GET.get("recording_start_time") else None
            )
            recording.start_time = recording_start_time

        loaded = recording.load_metadata()

        if not loaded:
            raise exceptions.NotFound("Recording not found")

        recording.load_person()

        if not request.user.is_anonymous:
            save_viewed = request.GET.get("save_view") is not None and not is_impersonated_session(request)
            recording.check_viewed_for_user(request.user, save_viewed=save_viewed)

        serializer = self.get_serializer(recording)

        return Response(serializer.data)

    def destroy(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        recording = self.get_object()

        if recording.deleted:
            raise exceptions.NotFound("Recording not found")

        recording.deleted = True
        recording.save()

        return Response({"success": True}, status=204)

    @action(methods=["GET"], detail=True)
    def snapshot_file(self, request: request.Request, **kwargs) -> HttpResponse:
        recording = self.get_object()

        if recording.deleted:
            raise exceptions.NotFound("Recording not found")

        blob_key = request.GET.get("blob_key")

        if not blob_key:
            raise exceptions.ValidationError("Must provide a snapshot file blob key")

        # very short-lived pre-signed URL
        file_key = f"session_recordings/team_id/{self.team.pk}/session_id/{self.kwargs['pk']}/data/{blob_key}"
        url = object_storage.get_presigned_url(file_key, expiration=60)
        if not url:
            raise exceptions.NotFound("Snapshot file not found")

        with requests.get(url=url, stream=True) as r:
            r.raise_for_status()
            response = HttpResponse(content=r.raw, content_type="application/json")
            response["Content-Disposition"] = "inline"
            return response

    # Paginated endpoint that returns the snapshots for the recording
    @action(methods=["GET"], detail=True)
    def snapshots(self, request: request.Request, **kwargs):
        recording = self.get_object()

        if recording.deleted:
            raise exceptions.NotFound("Recording not found")

        if request.GET.get("blob_loading_enabled", "false") == "true":
            blob_prefix = f"session_recordings/team_id/{self.team.pk}/session_id/{recording.session_id}/data/"
            blob_keys = object_storage.list_objects(blob_prefix)

            if blob_keys:
                return Response(
                    {
                        "snapshot_data_by_window_id": [],
                        "blob_keys": [x.replace(blob_prefix, "") for x in blob_keys],
                        "next": None,
                    }
                )

        # TODO: Why do we use a Filter? Just swap to norma, offset, limit pagination
        filter = Filter(request=request)
        limit = filter.limit if filter.limit else DEFAULT_RECORDING_CHUNK_LIMIT
        offset = filter.offset if filter.offset else 0

        # Optimisation step if passed to speed up retrieval of CH data
        if not recording.start_time:
            recording_start_time = (
                parser.parse(request.GET["recording_start_time"]) if request.GET.get("recording_start_time") else None
            )
            recording.start_time = recording_start_time

        recording.load_snapshots(limit, offset)

        if offset == 0:
            if not recording.snapshot_data_by_window_id:
                raise exceptions.NotFound("Snapshots not found")

        if recording.can_load_more_snapshots:
            next_url = format_query_params_absolute_url(request, offset + limit, limit) if True else None
        else:
            next_url = None

        res = {
            "storage": recording.storage,
            "next": next_url,
            "snapshot_data_by_window_id": recording.snapshot_data_by_window_id,
        }

        # NOTE: We have seen some issues with encoding of emojis, specifically when there is a lone "surrogate pair". See #13272 for more details
        # The Django JsonResponse handles this case, but the DRF Response does not. So we fall back to the Django JsonResponse if we encounter an error
        try:
            JSONRenderer().render(data=res)
        except Exception:
            capture_exception(
                Exception("DRF Json encoding failed, falling back to Django JsonResponse"), {"response_data": res}
            )
            return JsonResponse(res)

        return Response(res)

    # Returns properties given a list of session recording ids
    @action(methods=["GET"], detail=False)
    def properties(self, request: request.Request, **kwargs):
        filter = SessionRecordingsFilter(request=request, team=self.team)
        session_ids = [
            recording_id for recording_id in json.loads(self.request.GET.get("session_ids", "[]")) if recording_id
        ]
        for session_id in session_ids:
            if not isinstance(session_id, str):
                raise exceptions.ValidationError(f"Invalid session_id: {session_id} - not a string")
        session_recordings_properties = SessionRecordingProperties(
            team=self.team, filter=filter, session_ids=session_ids
        ).run()

        if not request.user.is_authenticated:  # for mypy
            raise exceptions.NotAuthenticated()

        session_recording_serializer = SessionRecordingPropertiesSerializer(
            data=session_recordings_properties, many=True
        )

        session_recording_serializer.is_valid(raise_exception=True)

        return Response({"results": session_recording_serializer.data})


def list_recordings(
    filter: SessionRecordingsFilter, request: request.Request, context: dict[str, Any], v2=False, v3=False
) -> dict:
    """
    As we can store recordings in S3 or in Clickhouse we need to do a few things here

    A. If filter.session_ids is specified:
      1. We first try to load them directly from Postgres if they have been persisted to S3 (they might have fell out of CH)
      2. Any that couldn't be found are then loaded from Clickhouse
    B. Otherwise we just load all values from Clickhouse
      2. Once loaded we convert them to SessionRecording objects in case we have any other persisted data
    """

    all_session_ids = filter.session_ids
    recordings: List[SessionRecording] = []
    more_recordings_available = False
    can_use_v2 = v2 and not any(entity.has_hogql_property for entity in filter.entities)
    can_use_v3 = v3 and not any(entity.has_hogql_property for entity in filter.entities)
    team = context["get_team"]()

    if all_session_ids:
        # If we specify the session ids (like from pinned recordings) we can optimise by only going to Postgres
        sorted_session_ids = sorted(all_session_ids)

        persisted_recordings_queryset = (
            SessionRecording.objects.filter(team=team, session_id__in=sorted_session_ids)
            .exclude(object_storage_path=None)
            .annotate(pinned_count=Count("playlist_items"))
        )

        persisted_recordings = persisted_recordings_queryset.all()

        recordings = recordings + list(persisted_recordings)

        remaining_session_ids = list(set(all_session_ids) - {x.session_id for x in persisted_recordings})
        filter = filter.shallow_clone({SESSION_RECORDINGS_FILTER_IDS: json.dumps(remaining_session_ids)})

    if (all_session_ids and filter.session_ids) or not all_session_ids:
        # Only go to clickhouse if we still have remaining specified IDs or we are not specifying IDs

        # TODO: once person on events is deployed, we can remove the check for hogql properties https://github.com/PostHog/posthog/pull/14458#discussion_r1135780372
        if can_use_v3:
            # check separately here to help mypy see that SessionRecordingListFromReplaySummary
            # is its own thing even though it is still stuck with inheritance until we can collapse
            # the number of listing mechanisms
            (ch_session_recordings, more_recordings_available) = SessionRecordingListFromReplaySummary(
                filter=filter, team=team
            ).run()
        else:
            session_recording_list_instance: Type[SessionRecordingList] = (
                SessionRecordingListV2 if can_use_v2 else SessionRecordingList
            )
            (ch_session_recordings, more_recordings_available) = session_recording_list_instance(
                filter=filter, team=team
            ).run()
        recordings_from_clickhouse = SessionRecording.get_or_build_from_clickhouse(team, ch_session_recordings)
        recordings = recordings + recordings_from_clickhouse

    recordings = [x for x in recordings if not x.deleted]

    # If we have specified session_ids we need to sort them by the order they were specified
    if all_session_ids:
        recordings = sorted(recordings, key=lambda x: cast(List[str], all_session_ids).index(x.session_id))

    if not request.user.is_authenticated:  # for mypy
        raise exceptions.NotAuthenticated()

    # Update the viewed status for all loaded recordings
    viewed_session_recordings = set(
        SessionRecordingViewed.objects.filter(team=team, user=request.user).values_list("session_id", flat=True)
    )

    # Get the related persons for all the recordings
    distinct_ids = sorted([x.distinct_id for x in recordings])
    person_distinct_ids = (
        PersonDistinctId.objects.filter(distinct_id__in=distinct_ids, team=team)
        .select_related("person")
        .prefetch_related(Prefetch("person__persondistinctid_set", to_attr="distinct_ids_cache"))
    )

    distinct_id_to_person = {}
    for person_distinct_id in person_distinct_ids:
        distinct_id_to_person[person_distinct_id.distinct_id] = person_distinct_id.person

    for recording in recordings:
        recording.viewed = recording.session_id in viewed_session_recordings
        recording.person = distinct_id_to_person.get(recording.distinct_id)

    session_recording_serializer = SessionRecordingSerializer(recordings, context=context, many=True)
    results = session_recording_serializer.data

    return {
        "results": results,
        "has_next": more_recordings_available,
        "version": 3 if can_use_v3 else 2 if can_use_v2 else 1,
    }
