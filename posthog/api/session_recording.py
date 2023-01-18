import json
from typing import Any, List, cast

import structlog
from dateutil import parser
from django.db.models import Count, Prefetch
from django.http import JsonResponse
from rest_framework import exceptions, request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from sentry_sdk import capture_exception

from posthog.api.person import PersonSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.constants import SESSION_RECORDINGS_FILTER_IDS
from posthog.models import Filter
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.person.person import PersonDistinctId
from posthog.models.session_recording.session_recording import SessionRecording
from posthog.models.session_recording_event import SessionRecordingViewed
from posthog.models.team.team import Team
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.queries.session_recordings.session_recording_list import SessionRecordingList
from posthog.queries.session_recordings.session_recording_properties import SessionRecordingProperties
from posthog.rate_limit import PassThroughClickHouseBurstRateThrottle, PassThroughClickHouseSustainedRateThrottle
from posthog.utils import format_query_params_absolute_url

DEFAULT_RECORDING_CHUNK_LIMIT = 20  # Should be tuned to find the best value

logger = structlog.get_logger(__name__)


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
            "segments",
            "start_and_end_times_by_window_id",
            "snapshot_data_by_window_id",
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
            "snapshot_data_by_window_id",
            "storage",
            "pinned_count",
        ]


class SessionRecordingPropertiesSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    properties = serializers.DictField(required=False)

    def to_representation(self, instance):
        return {
            "id": instance["session_id"],
            "properties": instance["properties"],
        }


class SessionRecordingViewSet(StructuredViewSetMixin, viewsets.ViewSet):
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    throttle_classes = [PassThroughClickHouseBurstRateThrottle, PassThroughClickHouseSustainedRateThrottle]

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        filter = SessionRecordingsFilter(request=request)
        return Response(list_recordings(filter, request, self.team))

    # Returns meta data about the recording
    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        recording = SessionRecording.get_or_build(session_id=kwargs["pk"], team=self.team)

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
        recording.check_viewed_for_user(request.user, save_viewed=request.GET.get("save_view") is not None)

        serializer = SessionRecordingSerializer(recording)

        return Response(serializer.data)

    # Paginated endpoint that returns the snapshots for the recording
    @action(methods=["GET"], detail=True)
    def snapshots(self, request: request.Request, **kwargs):
        # TODO: Why do we use a Filter? Just swap to norma, offset, limit pagination
        filter = Filter(request=request)
        limit = filter.limit if filter.limit else DEFAULT_RECORDING_CHUNK_LIMIT
        offset = filter.offset if filter.offset else 0

        recording = SessionRecording.get_or_build(session_id=kwargs["pk"], team=self.team)

        # Optimisation step if passed to speed up retrieval of CH data
        if not recording.start_time:
            recording_start_time = (
                parser.parse(request.GET["recording_start_time"]) if request.GET.get("recording_start_time") else None
            )
            recording.start_time = recording_start_time

        recording.load_snapshots(limit, offset)

        if not recording.snapshot_data_by_window_id:
            raise exceptions.NotFound("Snapshots not found")

        if recording.can_load_more_snapshots:
            next_url = format_query_params_absolute_url(request, offset + limit, limit) if True else None
        else:
            next_url = None

        res = {
            "next": next_url,
            "snapshot_data_by_window_id": recording.snapshot_data_by_window_id,
            # TODO: Remove this once the frontend is migrated to use the above values
            "result": {
                "next": next_url,
                "snapshot_data_by_window_id": recording.snapshot_data_by_window_id,
            },
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
        filter = SessionRecordingsFilter(request=request)
        session_ids = [
            recording_id for recording_id in json.loads(self.request.GET.get("session_ids", "[]")) if recording_id
        ]
        session_recordings_properties = SessionRecordingProperties(
            team=self.team, filter=filter, session_ids=session_ids, hogql_values={}
        ).run()

        if not request.user.is_authenticated:  # for mypy
            raise exceptions.NotAuthenticated()

        session_recording_serializer = SessionRecordingPropertiesSerializer(
            data=session_recordings_properties, many=True
        )

        session_recording_serializer.is_valid(raise_exception=True)

        return Response({"results": session_recording_serializer.data})


def list_recordings(filter: SessionRecordingsFilter, request: request.Request, team: Team) -> dict:
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

    if all_session_ids:
        # If we specify the session ids (like from pinned recordings) we can optimise by only going to Postgres
        persisted_recordings_queryset = (
            SessionRecording.objects.filter(team=team, session_id__in=all_session_ids)
            .exclude(object_storage_path=None)
            .annotate(pinned_count=Count("playlist_items"))
        )

        persisted_recordings = persisted_recordings_queryset.all()

        recordings = recordings + list(persisted_recordings)

        remaining_session_ids = list(set(all_session_ids) - {x.session_id for x in persisted_recordings})
        filter = filter.with_data({SESSION_RECORDINGS_FILTER_IDS: json.dumps(remaining_session_ids)})

    if (all_session_ids and filter.session_ids) or not all_session_ids:
        # Only go to clickhouse if we still have remaining specified IDs or we are not specifying IDs
        (ch_session_recordings, more_recordings_available) = SessionRecordingList(
            filter=filter, team=team, hogql_values={}
        ).run()
        recordings_from_clickhouse = SessionRecording.get_or_build_from_clickhouse(team, ch_session_recordings)
        recordings = recordings + recordings_from_clickhouse

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
    distinct_ids = [x.distinct_id for x in recordings]
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

    session_recording_serializer = SessionRecordingSerializer(recordings, many=True)
    results = session_recording_serializer.data

    return {"results": results, "has_next": more_recordings_available}
