import os
import time
from datetime import datetime, timedelta, timezone

import json
from typing import Any, List, Type, cast, Dict, Tuple

from django.conf import settings

import posthoganalytics
import requests
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import JsonResponse, HttpResponse
from drf_spectacular.utils import extend_schema
from loginas.utils import is_impersonated_session
from rest_framework import exceptions, request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.person import MinimalPersonSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import SharingAccessTokenAuthentication
from posthog.cloud_utils import is_cloud
from posthog.constants import SESSION_RECORDINGS_FILTER_IDS
from posthog.models import User
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.person.person import PersonDistinctId
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.models.session_recording_event import (
    SessionRecordingViewed,
)

from posthog.session_recordings.queries.session_recording_list_from_replay_summary import (
    SessionRecordingListFromReplaySummary,
    SessionIdEventsQuery,
)
from posthog.session_recordings.queries.session_recording_properties import (
    SessionRecordingProperties,
)
from posthog.rate_limit import (
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
)
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.session_recordings.realtime_snapshots import get_realtime_snapshots, publish_subscription
from posthog.session_recordings.session_summary.summarize_session import summarize_recording
from posthog.session_recordings.snapshots.convert_legacy_snapshots import (
    convert_original_version_lts_recording,
)
from posthog.storage import object_storage
from prometheus_client import Counter


SNAPSHOT_SOURCE_REQUESTED = Counter(
    "session_snapshots_requested_counter",
    "When calling the API and providing a concrete snapshot type to load.",
    labelnames=["source"],
)


# context manager for gathering a sequence of server timings
class ServerTimingsGathered:
    def __init__(self):
        # Instance level dictionary to store timings
        self.timings_dict = {}

    def __call__(self, name):
        self.name = name
        return self

    def __enter__(self):
        # timings are assumed to be in milliseconds when reported
        # but are gathered by time.perf_counter which is fractional seconds 🫠
        # so each value is multiplied by 1000 at collection
        self.start_time = time.perf_counter() * 1000

    def __exit__(self, exc_type, exc_val, exc_tb):
        end_time = time.perf_counter() * 1000
        elapsed_time = end_time - self.start_time
        self.timings_dict[self.name] = elapsed_time

    def get_all_timings(self):
        return self.timings_dict


class SessionRecordingSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source="session_id", read_only=True)
    recording_duration = serializers.IntegerField(source="duration", read_only=True)
    person = MinimalPersonSerializer(required=False)

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


def list_recordings_response(
    filter: SessionRecordingsFilter, request: request.Request, serializer_context: Dict[str, Any]
) -> Response:
    (recordings, timings) = list_recordings(filter, request, context=serializer_context)
    response = Response(recordings)
    response.headers["Server-Timing"] = ", ".join(
        f"{key};dur={round(duration, ndigits=2)}" for key, duration in timings.items()
    )
    return response


# NOTE: Could we put the sharing stuff in the shared mixin :thinking:
class SessionRecordingViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    base_scope = "session_recording"
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = SessionRecordingSerializer
    # We don't use this
    queryset = SessionRecording.objects.none()

    sharing_enabled_actions = ["retrieve", "snapshots", "snapshot_file"]

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
        return list_recordings_response(filter, request, self.get_serializer_context())

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

    @action(methods=["POST"], detail=True)
    def persist(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        recording = self.get_object()

        if not settings.EE_AVAILABLE:
            raise exceptions.ValidationError("LTS persistence is only available in the full version of PostHog")

        # Indicates it is not yet persisted
        # "Persistence" is simply saving a record in the DB currently - the actual save to S3 is done on a worker
        if recording.storage == "object_storage":
            recording.save()

        return Response({"success": True})

    @action(methods=["GET"], detail=True)
    def snapshots(self, request: request.Request, **kwargs):
        """
        Snapshots can be loaded from multiple places:
        1. From S3 if the session is older than our ingestion limit. This will be multiple files that can be streamed to the client
        2. or from Redis if the session is newer than our ingestion limit.

        Clients need to call this API twice.
        First without a source parameter to get a list of sources supported by the given session.
        And then once for each source in the returned list to get the actual snapshots.

        NB version 1 of this API has been deprecated and ClickHouse stored snapshots are no longer supported.
        """

        recording = self.get_object()

        if not SessionReplayEvents().exists(session_id=str(recording.session_id), team=self.team):
            raise exceptions.NotFound("Recording not found")

        response_data = {}
        source = request.GET.get("source")
        might_have_realtime = True
        newest_timestamp = None

        event_properties = {
            "team_id": self.team.pk,
            "request_source": source,
            "session_being_loaded": recording.session_id,
        }

        if request.headers.get("X-POSTHOG-SESSION-ID"):
            event_properties["$session_id"] = request.headers["X-POSTHOG-SESSION-ID"]

        posthoganalytics.capture(
            self._distinct_id_from_request(request),
            "v2 session recording snapshots viewed",
            event_properties,
        )

        if source:
            SNAPSHOT_SOURCE_REQUESTED.labels(source=source).inc()

        if not source:
            sources: List[dict] = []

            blob_keys: List[str] | None = None
            if recording.object_storage_path:
                if recording.storage_version == "2023-08-01":
                    blob_prefix = recording.object_storage_path
                    blob_keys = object_storage.list_objects(cast(str, blob_prefix))
                else:
                    # originally LTS files were in a single file
                    sources.append(
                        {
                            "source": "blob",
                            "start_timestamp": recording.start_time,
                            "end_timestamp": recording.end_time,
                            "blob_key": recording.object_storage_path,
                        }
                    )
                    might_have_realtime = False
            else:
                blob_prefix = recording.build_blob_ingestion_storage_path()
                blob_keys = object_storage.list_objects(blob_prefix)

            if blob_keys:
                for full_key in blob_keys:
                    # Keys are like 1619712000-1619712060
                    blob_key = full_key.replace(blob_prefix.rstrip("/") + "/", "")
                    time_range = [datetime.fromtimestamp(int(x) / 1000, tz=timezone.utc) for x in blob_key.split("-")]

                    sources.append(
                        {
                            "source": "blob",
                            "start_timestamp": time_range[0],
                            "end_timestamp": time_range.pop(),
                            "blob_key": blob_key,
                        }
                    )

            if sources:
                sources = sorted(sources, key=lambda x: x["start_timestamp"])
                oldest_timestamp = min(sources, key=lambda k: k["start_timestamp"])["start_timestamp"]
                newest_timestamp = min(sources, key=lambda k: k["end_timestamp"])["end_timestamp"]

                if might_have_realtime:
                    might_have_realtime = oldest_timestamp + timedelta(hours=24) > datetime.now(timezone.utc)

            if might_have_realtime:
                sources.append(
                    {
                        "source": "realtime",
                        "start_timestamp": newest_timestamp,
                        "end_timestamp": None,
                    }
                )
                # the UI will use this to try to load realtime snapshots
                # so, we can publish the request for Mr. Blobby to start syncing to Redis now
                # it takes a short while for the subscription to be sync'd into redis
                # let's use the network round trip time to get started
                publish_subscription(team_id=str(self.team.pk), session_id=str(recording.session_id))

            response_data["sources"] = sources

        elif source == "realtime":
            snapshots = get_realtime_snapshots(team_id=self.team.pk, session_id=str(recording.session_id)) or []

            event_properties["source"] = "realtime"
            event_properties["snapshots_length"] = len(snapshots)
            posthoganalytics.capture(
                self._distinct_id_from_request(request),
                "session recording snapshots v2 loaded",
                event_properties,
            )

            response_data["snapshots"] = snapshots

        elif source == "blob":
            blob_key = request.GET.get("blob_key", "")
            if not blob_key:
                raise exceptions.ValidationError("Must provide a snapshot file blob key")

            # very short-lived pre-signed URL
            if recording.object_storage_path:
                if recording.storage_version == "2023-08-01":
                    file_key = f"{recording.object_storage_path}/{blob_key}"
                else:
                    # this is a legacy recording, we need to load the file from the old path
                    file_key = convert_original_version_lts_recording(recording)
            else:
                file_key = (
                    f"session_recordings/team_id/{self.team.pk}/session_id/{recording.session_id}/data/{blob_key}"
                )
            url = object_storage.get_presigned_url(file_key, expiration=60)
            if not url:
                raise exceptions.NotFound("Snapshot file not found")

            event_properties["source"] = "blob"
            event_properties["blob_key"] = blob_key
            posthoganalytics.capture(
                self._distinct_id_from_request(request),
                "session recording snapshots v2 loaded",
                event_properties,
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

    @action(methods=["POST"], detail=True)
    def summarize(self, request: request.Request, **kwargs):
        if not request.user.is_authenticated:
            raise exceptions.NotAuthenticated()

        user = cast(User, request.user)

        cache_key = f'summarize_recording_{self.team.pk}_{self.kwargs["pk"]}'
        # Check if the response is cached
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)

        recording = self.get_object()

        if not SessionReplayEvents().exists(session_id=str(recording.session_id), team=self.team):
            raise exceptions.NotFound("Recording not found")

        environment_is_allowed = settings.DEBUG or is_cloud()
        has_openai_api_key = bool(os.environ.get("OPENAI_API_KEY"))
        if not environment_is_allowed or not has_openai_api_key:
            raise exceptions.ValidationError("session summary is only supported in PostHog Cloud")

        if not posthoganalytics.feature_enabled("ai-session-summary", str(user.distinct_id)):
            raise exceptions.ValidationError("session summary is not enabled for this user")

        summary = summarize_recording(recording, user, self.team)
        timings = summary.pop("timings", None)
        cache.set(cache_key, summary, timeout=30)

        posthoganalytics.capture(event="session summarized", distinct_id=str(user.distinct_id), properties=summary)

        # let the browser cache for half the time we cache on the server
        r = Response(summary, headers={"Cache-Control": "max-age=15"})
        if timings:
            r.headers["Server-Timing"] = ", ".join(
                f"{key};dur={round(duration, ndigits=2)}" for key, duration in timings.items()
            )
        return r


def list_recordings(
    filter: SessionRecordingsFilter, request: request.Request, context: Dict[str, Any]
) -> Tuple[Dict, Dict]:
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

    timer = ServerTimingsGathered()

    with timer("load_recordings_from_clickhouse"):
        if all_session_ids:
            # If we specify the session ids (like from pinned recordings) we can optimise by only going to Postgres
            sorted_session_ids = sorted(all_session_ids)

            persisted_recordings_queryset = SessionRecording.objects.filter(
                team=team, session_id__in=sorted_session_ids
            ).exclude(object_storage_path=None)

            persisted_recordings = persisted_recordings_queryset.all()

            recordings = recordings + list(persisted_recordings)

            remaining_session_ids = list(set(all_session_ids) - {x.session_id for x in persisted_recordings})
            filter = filter.shallow_clone({SESSION_RECORDINGS_FILTER_IDS: remaining_session_ids})

        if (all_session_ids and filter.session_ids) or not all_session_ids:
            # Only go to clickhouse if we still have remaining specified IDs, or we are not specifying IDs
            (
                ch_session_recordings,
                more_recordings_available,
            ) = SessionRecordingListFromReplaySummary(filter=filter, team=team).run()

            recordings_from_clickhouse = SessionRecording.get_or_build_from_clickhouse(team, ch_session_recordings)
            recordings = recordings + recordings_from_clickhouse

        recordings = [x for x in recordings if not x.deleted]

        # If we have specified session_ids we need to sort them by the order they were specified
        if all_session_ids:
            recordings = sorted(
                recordings,
                key=lambda x: cast(List[str], all_session_ids).index(x.session_id),
            )

    if not request.user.is_authenticated:  # for mypy
        raise exceptions.NotAuthenticated()

    # Update the viewed status for all loaded recordings
    viewed_session_recordings = set(
        SessionRecordingViewed.objects.filter(team=team, user=request.user).values_list("session_id", flat=True)
    )

    with timer("load_persons"):
        # Get the related persons for all the recordings
        distinct_ids = sorted([x.distinct_id for x in recordings])
        person_distinct_ids = PersonDistinctId.objects.filter(distinct_id__in=distinct_ids, team=team).select_related(
            "person"
        )

    with timer("process_persons"):
        distinct_id_to_person = {}
        for person_distinct_id in person_distinct_ids:
            person_distinct_id.person._distinct_ids = [
                person_distinct_id.distinct_id
            ]  # Stop the person from loading all distinct ids
            distinct_id_to_person[person_distinct_id.distinct_id] = person_distinct_id.person

        for recording in recordings:
            recording.viewed = recording.session_id in viewed_session_recordings
            recording.person = distinct_id_to_person.get(recording.distinct_id)

    session_recording_serializer = SessionRecordingSerializer(recordings, context=context, many=True)
    results = session_recording_serializer.data

    return (
        {"results": results, "has_next": more_recordings_available, "version": 3},
        timer.get_all_timings(),
    )
