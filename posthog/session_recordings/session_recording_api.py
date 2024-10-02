import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, UTC
from prometheus_client import Histogram
import json
from typing import Any, cast
from collections.abc import Generator

from django.conf import settings

import posthoganalytics
import requests
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.http import JsonResponse, HttpResponse
from drf_spectacular.utils import extend_schema
from loginas.utils import is_impersonated_session
from rest_framework import exceptions, request, serializers, viewsets
from posthog.api.utils import action
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.utils.encoders import JSONEncoder

from posthog.api.person import MinimalPersonSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import safe_clickhouse_string
from posthog.auth import SharingAccessTokenAuthentication
from posthog.cloud_utils import is_cloud
from posthog.constants import SESSION_RECORDINGS_FILTER_IDS
from posthog.models import User, Team
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.person.person import PersonDistinctId
from posthog.schema import QueryTiming, HogQLQueryModifiers
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.models.session_recording_event import (
    SessionRecordingViewed,
)

from posthog.session_recordings.queries.session_recording_list_from_filters import (
    SessionRecordingListFromFilters,
    ReplayFiltersEventsSubQuery,
)
from posthog.session_recordings.queries.session_recording_properties import (
    SessionRecordingProperties,
)
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle, PersonalApiKeyRateThrottle
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.session_recordings.realtime_snapshots import get_realtime_snapshots, publish_subscription
from ee.session_recordings.session_summary.summarize_session import summarize_recording
from ee.session_recordings.ai.similar_recordings import similar_recordings
from ee.session_recordings.ai.error_clustering import error_clustering
from posthog.session_recordings.snapshots.convert_legacy_snapshots import convert_original_version_lts_recording
from posthog.storage import object_storage
from prometheus_client import Counter
from posthog.auth import PersonalAPIKeyAuthentication

SNAPSHOTS_BY_PERSONAL_API_KEY_COUNTER = Counter(
    "snapshots_personal_api_key_counter",
    "Requests for recording snapshots per personal api key",
    labelnames=["api_key", "source"],
)

SNAPSHOT_SOURCE_REQUESTED = Counter(
    "session_snapshots_requested_counter",
    "When calling the API and providing a concrete snapshot type to load.",
    labelnames=["source"],
)

GENERATE_PRE_SIGNED_URL_HISTOGRAM = Histogram(
    "session_snapshots_generate_pre_signed_url_histogram",
    "Time taken to generate a pre-signed URL for a session snapshot",
)

GET_REALTIME_SNAPSHOTS_FROM_REDIS = Histogram(
    "session_snapshots_get_realtime_snapshots_from_redis_histogram",
    "Time taken to get realtime snapshots from Redis",
)

STREAM_RESPONSE_TO_CLIENT_HISTOGRAM = Histogram(
    "session_snapshots_stream_response_to_client_histogram",
    "Time taken to stream a session snapshot to the client",
)


class SurrogatePairSafeJSONEncoder(JSONEncoder):
    def encode(self, o):
        return safe_clickhouse_string(super().encode(o), with_counter=False)


class SurrogatePairSafeJSONRenderer(JSONRenderer):
    """
    Blob snapshots are compressed data which we pass through from blob storage.
    Realtime snapshot API returns "bare" JSON from Redis.
    We can be sure that the "bare" data could contain surrogate pairs
    from the browser's console logs.

    This JSON renderer ensures that the stringified JSON does not have any unescaped surrogate pairs.

    Because it has to override the encoder, it can't use orjson.
    """

    encoder_class = SurrogatePairSafeJSONEncoder


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

    ongoing = serializers.SerializerMethodField()
    viewed = serializers.SerializerMethodField()

    def get_ongoing(self, obj: SessionRecording) -> bool:
        # ongoing is a custom field that we add if loading from ClickHouse
        return getattr(obj, "ongoing", False)

    def get_viewed(self, obj: SessionRecording) -> bool:
        # viewed is a custom field that we load from PG Sql and merge into the model
        return getattr(obj, "viewed", False)

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
            "snapshot_source",
            "ongoing",
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
            "snapshot_source",
            "ongoing",
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


class SessionRecordingSourcesSerializer(serializers.Serializer):
    sources = serializers.ListField(child=SessionRecordingSnapshotsSourceSerializer(), required=False)
    snapshots = serializers.ListField(required=False)


def list_recordings_response(
    filter: SessionRecordingsFilter, request: request.Request, serializer_context: dict[str, Any]
) -> Response:
    (recordings, timings) = list_recordings(filter, request, context=serializer_context)
    response = Response(recordings)
    response.headers["Server-Timing"] = ", ".join(
        f"{key};dur={round(duration, ndigits=2)}" for key, duration in timings.items()
    )
    return response


def ensure_not_weak(etag: str) -> str:
    """
    minio at least doesn't like weak etags, so we need to strip the W/ prefix if it exists.
    we don't really care about the semantic difference between a strong and a weak etag here,
    so we can just strip it.
    """
    if etag.startswith("W/"):
        return etag[2:].lstrip('"').rstrip('"')
    return etag


@contextmanager
def stream_from(url: str, headers: dict | None = None) -> Generator[requests.Response, None, None]:
    """
    Stream data from a URL using optional headers.

    Tricky: mocking the requests library, so we can control the response here is a bit of a pain.
    the mocks are complex to write, so tests fail when the code actually works
    by wrapping this interaction we can mock this method
    instead of trying to mock the internals of the requests library
    """
    if headers is None:
        headers = {}

    session = requests.Session()

    try:
        response = session.get(url, headers=headers, stream=True)
        yield response
    finally:
        session.close()


class SnapshotsBurstRateThrottle(PersonalApiKeyRateThrottle):
    scope = "snapshots_burst"
    rate = "120/minute"


class SnapshotsSustainedRateThrottle(PersonalApiKeyRateThrottle):
    scope = "snapshots_sustained"
    rate = "600/hour"


# NOTE: Could we put the sharing stuff in the shared mixin :thinking:
class SessionRecordingViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "session_recording"
    scope_object_read_actions = ["list", "retrieve", "snapshots"]
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]
    serializer_class = SessionRecordingSerializer
    # We don't use this
    queryset = SessionRecording.objects.none()

    sharing_enabled_actions = ["retrieve", "snapshots", "snapshot_file"]

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if isinstance(self.request.successful_authenticator, SharingAccessTokenAuthentication):
            return SessionRecordingSharedSerializer
        else:
            return SessionRecordingSerializer

    def safely_get_object(self, queryset) -> SessionRecording:
        recording = SessionRecording.get_or_build(session_id=self.kwargs["pk"], team=self.team)

        if recording.deleted:
            raise exceptions.NotFound("Recording not found")

        return recording

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        filter = SessionRecordingsFilter(request=request, team=self.team)
        return list_recordings_response(filter, request, self.get_serializer_context())

    @extend_schema(
        exclude=True,
        description="""
        Gets a list of event ids that match the given session recording filter.
        The filter must include a single session ID.
        And must include at least one event or action filter.
        This API is intended for internal use and might have unannounced breaking changes.""",
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

        distinct_id = str(cast(User, request.user).distinct_id)
        modifiers = safely_read_modifiers_overrides(distinct_id, self.team)
        matching_events_query_response = ReplayFiltersEventsSubQuery(
            filter=filter, team=self.team, hogql_query_modifiers=modifiers
        ).get_event_ids_for_session()

        response = JsonResponse(data={"results": matching_events_query_response.results})

        response.headers["Server-Timing"] = ", ".join(
            f"{key};dur={round(duration, ndigits=2)}"
            for key, duration in _generate_timings(
                matching_events_query_response.timings, ServerTimingsGathered()
            ).items()
        )
        return response

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

    @extend_schema(exclude=True)
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

    @extend_schema(exclude=True)
    @action(
        methods=["GET"],
        detail=True,
        renderer_classes=[SurrogatePairSafeJSONRenderer],
        throttle_classes=[SnapshotsBurstRateThrottle, SnapshotsSustainedRateThrottle],
    )
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

        source = request.GET.get("source")

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

        personal_api_key = PersonalAPIKeyAuthentication.find_key_with_source(request)
        if personal_api_key:
            SNAPSHOTS_BY_PERSONAL_API_KEY_COUNTER.labels(api_key=personal_api_key, source=source).inc()

        if not source:
            return self._gather_session_recording_sources(recording)
        elif source == "realtime":
            return self._send_realtime_snapshots_to_client(recording, request, event_properties)
        elif source == "blob":
            return self._stream_blob_to_client(recording, request, event_properties)
        else:
            raise exceptions.ValidationError("Invalid source must be one of [realtime, blob]")

    def _gather_session_recording_sources(self, recording: SessionRecording) -> Response:
        might_have_realtime = True
        newest_timestamp = None
        response_data = {}
        sources: list[dict] = []
        blob_keys: list[str] | None = None
        blob_prefix = ""

        if recording.object_storage_path:
            if recording.storage_version == "2023-08-01":
                blob_prefix = recording.object_storage_path
                blob_keys = object_storage.list_objects(cast(str, blob_prefix))
            else:
                # originally LTS files were in a single file
                # TODO this branch can be deleted after 01-08-2024
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
                blob_key_base = blob_key.split(".")[0]  # Remove the extension if it exists
                time_range = [datetime.fromtimestamp(int(x) / 1000, tz=UTC) for x in blob_key_base.split("-")]

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
                might_have_realtime = oldest_timestamp + timedelta(hours=24) > datetime.now(UTC)
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
        serializer = SessionRecordingSourcesSerializer(response_data)
        return Response(serializer.data)

    @staticmethod
    def _validate_blob_key(blob_key: Any) -> None:
        if not blob_key:
            raise exceptions.ValidationError("Must provide a snapshot file blob key")

        if not isinstance(blob_key, str):
            raise exceptions.ValidationError("Invalid blob key: " + blob_key)

        # blob key should be a string of the form 1619712000-1619712060
        if not all(x.isdigit() for x in blob_key.split("-")):
            raise exceptions.ValidationError("Invalid blob key: " + blob_key)

    @staticmethod
    def _distinct_id_from_request(request):
        if isinstance(request.user, AnonymousUser):
            return request.GET.get("sharing_access_token") or "anonymous"
        elif isinstance(request.user, User):
            return str(request.user.distinct_id)
        else:
            return "anonymous"

    # Returns properties given a list of session recording ids
    @extend_schema(exclude=True)
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

    @extend_schema(exclude=True)
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

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=True)
    def similar_sessions(self, request: request.Request, **kwargs):
        if not request.user.is_authenticated:
            raise exceptions.NotAuthenticated()

        cache_key = f'similar_sessions_{self.team.pk}_{self.kwargs["pk"]}'
        # Check if the response is cached
        cached_response = cache.get(cache_key)
        if cached_response:
            return Response(cached_response)

        user = cast(User, request.user)

        if not posthoganalytics.feature_enabled("session-replay-similar-recordings", str(user.distinct_id)):
            raise exceptions.ValidationError("similar recordings is not enabled for this user")

        recording = self.get_object()

        if not SessionReplayEvents().exists(session_id=str(recording.session_id), team=self.team):
            raise exceptions.NotFound("Recording not found")

        recordings = similar_recordings(recording, self.team)
        if recordings:
            cache.set(cache_key, recordings, timeout=30)

        # let the browser cache for half the time we cache on the server
        r = Response(recordings, headers={"Cache-Control": "max-age=15"})
        return r

    @extend_schema(exclude=True)
    @action(methods=["GET"], detail=False)
    def error_clusters(self, request: request.Request, **kwargs):
        if not request.user.is_authenticated:
            raise exceptions.NotAuthenticated()

        refresh_clusters = request.GET.get("refresh")

        cache_key = f"cluster_errors_{self.team.pk}"
        # Check if the response is cached
        cached_response = cache.get(cache_key)
        if cached_response and not refresh_clusters:
            return Response(cached_response)

        user = cast(User, request.user)

        if not posthoganalytics.feature_enabled("session-replay-error-clustering", str(user.distinct_id)):
            raise exceptions.ValidationError("clustered errors is not enabled for this user")

        # Clustering will eventually be done during a scheduled background task
        clusters = error_clustering(self.team)

        if clusters:
            cache.set(cache_key, clusters, settings.CACHED_RESULTS_TTL)

        # let the browser cache for half the time we cache on the server
        r = Response(clusters, headers={"Cache-Control": "max-age=15"})
        return r

    def _stream_blob_to_client(
        self, recording: SessionRecording, request: request.Request, event_properties: dict
    ) -> HttpResponse:
        blob_key = request.GET.get("blob_key", "")
        self._validate_blob_key(blob_key)

        # very short-lived pre-signed URL
        with GENERATE_PRE_SIGNED_URL_HISTOGRAM.time():
            if recording.object_storage_path:
                if recording.storage_version == "2023-08-01":
                    file_key = f"{recording.object_storage_path}/{blob_key}"
                else:
                    # this is a legacy recording, we need to load the file from the old path
                    file_key = convert_original_version_lts_recording(recording)
            else:
                blob_prefix = settings.OBJECT_STORAGE_SESSION_RECORDING_BLOB_INGESTION_FOLDER
                file_key = f"{blob_prefix}/team_id/{self.team.pk}/session_id/{recording.session_id}/data/{blob_key}"
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

        with STREAM_RESPONSE_TO_CLIENT_HISTOGRAM.time():
            # streams the file from S3 to the client
            # will not decompress the possibly large file because of `stream=True`
            #
            # we pass some headers through to the client
            # particularly we should signal the content-encoding
            # to help the client know it needs to decompress
            #
            # if the client provides an e-tag we can use it to check if the file has changed
            # object store will respect this and send back 304 if the file hasn't changed,
            # and we don't need to send the large file over the wire

            if_none_match = request.headers.get("If-None-Match")
            headers = {}
            if if_none_match:
                headers["If-None-Match"] = ensure_not_weak(if_none_match)

            with stream_from(url=url, headers=headers) as streaming_response:
                streaming_response.raise_for_status()

                response = HttpResponse(content=streaming_response.raw, status=streaming_response.status_code)

                etag = streaming_response.headers.get("ETag")
                if etag:
                    response["ETag"] = ensure_not_weak(etag)

                # blobs are immutable, _really_ we can cache forever
                # but let's cache for an hour since people won't re-watch too often
                # we're setting cache control and ETag which might be considered overkill,
                # but it helps avoid network latency from the client to PostHog, then to object storage, and back again
                # when a client has a fresh copy
                response["Cache-Control"] = streaming_response.headers.get("Cache-Control") or "max-age=3600"

                response["Content-Type"] = "application/json"
                response["Content-Disposition"] = "inline"

                return response

    def _send_realtime_snapshots_to_client(
        self, recording: SessionRecording, request: request.Request, event_properties: dict
    ) -> HttpResponse | Response:
        version = request.GET.get("version", "og")

        with GET_REALTIME_SNAPSHOTS_FROM_REDIS.time():
            snapshot_lines = (
                get_realtime_snapshots(
                    team_id=self.team.pk,
                    session_id=str(recording.session_id),
                )
                or []
            )

        event_properties["source"] = "realtime"
        event_properties["snapshots_length"] = len(snapshot_lines)
        posthoganalytics.capture(
            self._distinct_id_from_request(request),
            "session recording snapshots v2 loaded",
            event_properties,
        )

        if version == "og":
            # originally we returned a list of dictionaries
            # under a snapshot key
            # we keep doing this here for a little while
            # so that existing browser sessions, that don't know about the new format
            # can carry on working until the next refresh
            serializer = SessionRecordingSourcesSerializer({"snapshots": [json.loads(s) for s in snapshot_lines]})
            return Response(serializer.data)
        elif version == "2024-04-30":
            response = HttpResponse(
                # convert list to a jsonl response
                content=("\n".join(snapshot_lines)),
                content_type="application/json",
            )
            # the browser is not allowed to cache this at all
            response["Cache-Control"] = "no-store"
            return response
        else:
            raise exceptions.ValidationError(f"Invalid version: {version}")


def list_recordings(
    filter: SessionRecordingsFilter, request: request.Request, context: dict[str, Any]
) -> tuple[dict, dict]:
    """
    As we can store recordings in S3 or in Clickhouse we need to do a few things here

    A. If filter.session_ids is specified:
      1. We first try to load them directly from Postgres if they have been persisted to S3 (they might have fell out of CH)
      2. Any that couldn't be found are then loaded from Clickhouse
    B. Otherwise we just load all values from Clickhouse
      2. Once loaded we convert them to SessionRecording objects in case we have any other persisted data
    """

    all_session_ids = filter.session_ids

    recordings: list[SessionRecording] = []
    more_recordings_available = False
    team = context["get_team"]()
    hogql_timings: list[QueryTiming] | None = None

    timer = ServerTimingsGathered()

    if all_session_ids:
        with timer("load_persisted_recordings"):
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
        distinct_id = str(cast(User, request.user).distinct_id)
        modifiers = safely_read_modifiers_overrides(distinct_id, team)

        with timer("load_recordings_from_hogql"):
            (ch_session_recordings, more_recordings_available, hogql_timings) = SessionRecordingListFromFilters(
                filter=filter, team=team, hogql_query_modifiers=modifiers
            ).run()

        with timer("build_recordings"):
            recordings_from_clickhouse = SessionRecording.get_or_build_from_clickhouse(team, ch_session_recordings)
            recordings = recordings + recordings_from_clickhouse

            recordings = [x for x in recordings if not x.deleted]

            # If we have specified session_ids we need to sort them by the order they were specified
            if all_session_ids:
                recordings = sorted(
                    recordings,
                    key=lambda x: cast(list[str], all_session_ids).index(x.session_id),
                )

    if not request.user.is_authenticated:  # for mypy
        raise exceptions.NotAuthenticated()

    # Update the viewed status for all loaded recordings
    with timer("load_viewed_recordings"):
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
            person = distinct_id_to_person.get(recording.distinct_id)
            if person:
                recording.person = person

    session_recording_serializer = SessionRecordingSerializer(recordings, context=context, many=True)
    results = session_recording_serializer.data

    all_timings = _generate_timings(hogql_timings, timer)
    return (
        {"results": results, "has_next": more_recordings_available, "version": 3},
        all_timings,
    )


def safely_read_modifiers_overrides(distinct_id: str, team: Team) -> HogQLQueryModifiers:
    modifiers = HogQLQueryModifiers()

    try:
        groups = {"organization": str(team.organization.id)}
        flag_key = "HOG_QL_ORG_QUERY_OVERRIDES"
        flags_n_bags = posthoganalytics.get_all_flags_and_payloads(
            distinct_id,
            groups=groups,
        )
        # this loads nothing whereas the payload is available
        # modifier_overrides = posthoganalytics.get_feature_flag_payload(
        #     flag_key,
        #     distinct_id,
        #     groups=groups,
        # )
        modifier_overrides = (flags_n_bags or {}).get("featureFlagPayloads", {}).get(flag_key, None)
        if modifier_overrides:
            modifiers.optimizeJoinedFilters = json.loads(modifier_overrides).get("optimizeJoinedFilters", None)
    except:
        # be extra safe
        pass

    return modifiers


def _generate_timings(hogql_timings: list[QueryTiming] | None, timer: ServerTimingsGathered) -> dict[str, float]:
    timings_dict = timer.get_all_timings()
    hogql_timings_dict = {}
    for key, value in hogql_timings or {}:
        new_key = f"hogql_{key[1].lstrip('./').replace('/', '_')}"
        # HogQL query timings are in seconds, convert to milliseconds
        hogql_timings_dict[new_key] = value[1] * 1000
    all_timings = {**timings_dict, **hogql_timings_dict}
    return all_timings
