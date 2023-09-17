from datetime import datetime, timedelta

import json
from typing import Any, List, Type, cast

import posthoganalytics
from dateutil import parser
import requests
from django.contrib.auth.models import AnonymousUser
from django.db.models import Count, Prefetch
from django.http import JsonResponse, HttpResponse
from drf_spectacular.utils import extend_schema
from loginas.utils import is_impersonated_session
from rest_framework import exceptions, request, serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from sentry_sdk import capture_exception

from posthog.api.person import PersonSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.auth import SharingAccessTokenAuthentication
from posthog.constants import SESSION_RECORDINGS_FILTER_IDS
from posthog.models import Filter, User
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.person.person import PersonDistinctId
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.permissions import (
    ProjectMembershipNecessaryPermissions,
    SharingTokenPermission,
    TeamMemberAccessPermission,
)
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed

from posthog.session_recordings.queries.session_recording_list_from_replay_summary import (
    SessionRecordingListFromReplaySummary,
    SessionIdEventsQuery,
)
from posthog.session_recordings.queries.session_recording_properties import SessionRecordingProperties
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.session_recordings.realtime_snapshots import get_realtime_snapshots
from posthog.storage import object_storage
from posthog.utils import format_query_params_absolute_url
from prometheus_client import Counter

DEFAULT_RECORDING_CHUNK_LIMIT = 20  # Should be tuned to find the best value

SNAPSHOT_SOURCE_REQUESTED = Counter(
    "session_snapshots_requested_counter",
    "When calling the API and providing a concrete snapshot type to load.",
    labelnames=["source"],
)


def snapshots_response(data: Any) -> Any:
    # NOTE: We have seen some issues with encoding of emojis, specifically when there is a lone "surrogate pair". See #13272 for more details
    # The Django JsonResponse handles this case, but the DRF Response does not. So we fall back to the Django JsonResponse if we encounter an error
    try:
        JSONRenderer().render(data=data)
    except Exception:
        capture_exception(
            Exception("DRF Json encoding failed, falling back to Django JsonResponse"), {"response_data": data}
        )
        return JsonResponse(data)

    return Response(data)


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
            "active_seconds",
            "inactive_seconds",
            "start_time",
            "end_time",
            "click_count",
            "keypress_count",
            "mouse_activity_count",
            "console_log_count",
            "console_warn_count",
            "console_error_count",
            "start_url",
            "person",
            "storage",
            "pinned_count",
        ]

        read_only_fields = [
            "id",
            "distinct_id",
            "viewed",
            "recording_duration",
            "active_seconds",
            "inactive_seconds",
            "start_time",
            "end_time",
            "click_count",
            "keypress_count",
            "mouse_activity_count",
            "console_log_count",
            "console_warn_count",
            "console_error_count",
            "start_url",
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


class SessionRecordingSnapshotsSourceSerializer(serializers.Serializer):
    source = serializers.CharField()  # type: ignore
    start_timestamp = serializers.DateTimeField(allow_null=True)
    end_timestamp = serializers.DateTimeField(allow_null=True)
    blob_key = serializers.CharField(allow_null=True)


class SessionRecordingSnapshotsSerializer(serializers.Serializer):
    sources = serializers.ListField(child=SessionRecordingSnapshotsSourceSerializer(), required=False)
    snapshots = serializers.ListField(required=False)


class SessionRecordingViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = SessionRecordingSerializer

    sharing_enabled_actions = ["retrieve", "snapshots", "snapshot_file"]

    def get_permissions(self):
        if isinstance(self.request.successful_authenticator, SharingAccessTokenAuthentication):
            return [SharingTokenPermission()]
        return super().get_permissions()

    def get_authenticators(self):
        return [SharingAccessTokenAuthentication(), *super().get_authenticators()]

    def get_serializer_class(self) -> Type[serializers.Serializer]:
        if isinstance(self.request.successful_authenticator, SharingAccessTokenAuthentication):
            return SessionRecordingSharedSerializer
        else:
            return SessionRecordingSerializer

    def get_object(self) -> SessionRecording:
        recording = SessionRecording.get_or_build(session_id=self.kwargs["pk"], team=self.team)

        if recording.deleted:
            raise exceptions.NotFound("Recording not found")

        self.check_object_permissions(self.request, recording)

        return recording

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        filter = SessionRecordingsFilter(request=request, team=self.team)

        return Response(list_recordings(filter, request, context=self.get_serializer_context()))

    @extend_schema(
        description="""
        Gets a list of event ids that match the given session recording filter.
        The filter must include a single session ID.
        And must include at least one event or action filter.
        This API is intended for internal use and might have unannounced breaking changes."""
    )
    @action(methods=["GET"], detail=False)
    def matching_events(self, request: request.Request, *args: Any, **kwargs: Any) -> JsonResponse:
        filter = SessionRecordingsFilter(request=request, team=self.team)

        if not filter.session_ids or len(filter.session_ids) != 1:
            raise exceptions.ValidationError(
                "Must specify exactly one session_id",
            )

        if not filter.events and not filter.actions:
            raise exceptions.ValidationError(
                "Must specify at least one event or action filter",
            )

        matching_events: List[str] = SessionIdEventsQuery(filter=filter, team=self.team).matching_events()
        return JsonResponse(data={"results": matching_events})

    # Returns metadata about the recording
    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        recording = self.get_object()

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

    def _snapshots_v2(self, request: request.Request):
        """
        This will eventually replace the snapshots endpoint below.
        This path only supports loading from S3 or Redis based on query params
        """

        recording = self.get_object()
        response_data = {}
        source = request.GET.get("source")

        event_properties = {
            "team_id": self.team.pk,
            "request_source": source,
            "session_being_loaded": recording.session_id,
        }

        if request.headers.get("X-POSTHOG-SESSION-ID"):
            event_properties["$session_id"] = request.headers["X-POSTHOG-SESSION-ID"]

        posthoganalytics.capture(
            self._distinct_id_from_request(request), "v2 session recording snapshots viewed", event_properties
        )

        if source:
            SNAPSHOT_SOURCE_REQUESTED.labels(source=source).inc()

        if not source:
            sources: List[dict] = []
            blob_prefix = recording.build_blob_ingestion_storage_path()
            blob_keys = object_storage.list_objects(blob_prefix)

            if not blob_keys and recording.storage_version == "2023-08-01":
                blob_prefix = recording.object_storage_path
                blob_keys = object_storage.list_objects(cast(str, blob_prefix))

            if blob_keys:
                for full_key in blob_keys:
                    # Keys are like 1619712000-1619712060
                    blob_key = full_key.replace(blob_prefix.rstrip("/") + "/", "")
                    time_range = [datetime.fromtimestamp(int(x) / 1000) for x in blob_key.split("-")]

                    sources.append(
                        {
                            "source": "blob",
                            "start_timestamp": time_range[0],
                            "end_timestamp": time_range.pop(),
                            "blob_key": blob_key,
                        }
                    )

            might_have_realtime = True
            newest_timestamp = None

            if sources:
                sources = sorted(sources, key=lambda x: x["start_timestamp"])
                oldest_timestamp = min(sources, key=lambda k: k["start_timestamp"])["start_timestamp"]
                newest_timestamp = min(sources, key=lambda k: k["end_timestamp"])["end_timestamp"]

                might_have_realtime = oldest_timestamp + timedelta(hours=24) > datetime.utcnow()

            if might_have_realtime:
                sources.append(
                    {
                        "source": "realtime",
                        "start_timestamp": newest_timestamp,
                        "end_timestamp": None,
                    }
                )

            response_data["sources"] = sources

        elif source == "realtime":
            snapshots = get_realtime_snapshots(team_id=self.team.pk, session_id=str(recording.session_id)) or []

            event_properties["source"] = "realtime"
            event_properties["snapshots_length"] = len(snapshots)
            posthoganalytics.capture(
                self._distinct_id_from_request(request), "session recording snapshots v2 loaded", event_properties
            )

            response_data["snapshots"] = snapshots

        elif source == "blob":
            blob_key = request.GET.get("blob_key", "")
            if not blob_key:
                raise exceptions.ValidationError("Must provide a snapshot file blob key")

            # very short-lived pre-signed URL
            file_key = f"session_recordings/team_id/{self.team.pk}/session_id/{recording.session_id}/data/{blob_key}"
            url = object_storage.get_presigned_url(file_key, expiration=60)
            if not url:
                raise exceptions.NotFound("Snapshot file not found")

            event_properties["source"] = "blob"
            event_properties["blob_key"] = blob_key
            posthoganalytics.capture(
                self._distinct_id_from_request(request), "session recording snapshots v2 loaded", event_properties
            )

            with requests.get(url=url, stream=True) as r:
                r.raise_for_status()
                response = HttpResponse(content=r.raw, content_type="application/json")
                response["Content-Disposition"] = "inline"
                return response
        else:
            raise exceptions.ValidationError("Invalid source must be one of [realtime, blob]")

        serializer = SessionRecordingSnapshotsSerializer(response_data)

        return Response(serializer.data)

    @action(methods=["GET"], detail=True)
    def snapshots(self, request: request.Request, **kwargs):
        """
        Snapshots can be loaded from multiple places:
        1. From S3 if the session is older than our ingestion limit. This will be multiple files that can be streamed to the client
        2. From Redis if the session is newer than our ingestion limit.
        3. From Clickhouse whilst we are migrating to the new ingestion method

        NB calling this API without `version=2` in the query params or with no version is deprecated and will be removed in the future
        """

        if request.GET.get("version") == "2":
            return self._snapshots_v2(request)

        recording = self.get_object()

        # TODO: Determine if we should try Redis or not based on the recording start time and the S3 responses

        if recording.deleted:
            raise exceptions.NotFound("Recording not found")

        if recording.storage_version:
            # we're only expected recordings with no snapshot version here
            # but a bad assumption about when we could create recordings with a snapshot version
            # of 2023-08-01 means we need to "force upgrade" these requests to version 2 of the API
            # so, we issue a temporary redirect to the same URL request but with version 2 in the query params
            params = request.GET.copy()
            params["version"] = "2"
            return Response(status=status.HTTP_302_FOUND, headers={"Location": f"{request.path}?{params.urlencode()}"})

        # TODO: Why do we use a Filter? Just swap to norma, offset, limit pagination
        filter = Filter(request=request)
        limit = filter.limit if filter.limit else DEFAULT_RECORDING_CHUNK_LIMIT
        offset = filter.offset if filter.offset else 0

        event_properties = {"team_id": self.team.pk, "session_being_loaded": recording.session_id, "offset": offset}

        if request.headers.get("X-POSTHOG-SESSION-ID"):
            event_properties["$session_id"] = request.headers["X-POSTHOG-SESSION-ID"]

        posthoganalytics.capture(
            self._distinct_id_from_request(request), "v1 session recording snapshots viewed", event_properties
        )

        # Optimisation step if passed to speed up retrieval of CH data
        if not recording.start_time:
            recording_start_time = (
                parser.parse(request.GET["recording_start_time"]) if request.GET.get("recording_start_time") else None
            )
            recording.start_time = recording_start_time

        try:
            recording.load_snapshots(limit, offset)
        except NotImplementedError as e:
            capture_exception(e)
            raise exceptions.NotFound("Storage version 2023-08-01 can only be accessed via V2 of this endpoint")

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

        return snapshots_response(res)

    @staticmethod
    def _distinct_id_from_request(request):
        if isinstance(request.user, AnonymousUser):
            return request.GET.get("sharing_access_token") or "anonymous"
        elif isinstance(request.user, User):
            return str(request.user.distinct_id)
        else:
            return "anonymous"

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


def list_recordings(filter: SessionRecordingsFilter, request: request.Request, context: dict[str, Any]) -> dict:
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
        # Only go to clickhouse if we still have remaining specified IDs, or we are not specifying IDs
        (ch_session_recordings, more_recordings_available) = SessionRecordingListFromReplaySummary(
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

    return {"results": results, "has_next": more_recordings_available, "version": 3}
