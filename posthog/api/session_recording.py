import json
from typing import Any

import structlog
from django.http import JsonResponse
from rest_framework import exceptions, request, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from sentry_sdk import capture_exception

from posthog.api.person import PersonSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.models import Filter, PersonDistinctId
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
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
            "storage",
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

        recording.load_metadata()
        recording.check_viewed_for_user(request.user)

        # recording_start_time_string = request.GET.get("recording_start_time")
        # recording_start_time = parser.parse(recording_start_time_string) if recording_start_time_string else None

        if request.GET.get("save_view"):
            # TODO: Move this into SessionRecording model maybe?
            SessionRecordingViewed.objects.get_or_create(
                team=self.team, user=request.user, session_id=recording.session_id
            )

        serializer = SessionRecordingSerializer(recording)

        return Response(serializer.data)

    # Paginated endpoint that returns the snapshots for the recording
    @action(methods=["GET"], detail=True)
    def snapshots(self, request: request.Request, **kwargs):
        # TODO: Why do we use a Filter? Just swap to norma, offset, limit pagination
        filter = Filter(request=request)
        limit = filter.limit if filter.limit else DEFAULT_RECORDING_CHUNK_LIMIT
        offset = filter.offset if filter.offset else 0

        # recording_start_time_string = request.GET.get("recording_start_time")
        # recording_start_time = parser.parse(recording_start_time_string) if recording_start_time_string else None

        recording = SessionRecording.get_or_build(session_id=kwargs["pk"], team=self.team)
        recording.load_snapshots(limit, offset)

        if recording.snapshot_data_by_window_id:
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
        else:
            res = {
                "next": None,
                "snapshot_data_by_window_id": None,
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
            team=self.team, filter=filter, session_ids=session_ids
        ).run()

        if not request.user.is_authenticated:  # for mypy
            raise exceptions.NotAuthenticated()

        session_recording_serializer = SessionRecordingPropertiesSerializer(
            data=session_recordings_properties, many=True
        )

        session_recording_serializer.is_valid(raise_exception=True)

        return Response({"results": session_recording_serializer.data})


def list_recordings(filter: SessionRecordingsFilter, request: request.Request, team: Team) -> dict:
    (ch_session_recordings, more_recordings_available) = SessionRecordingList(filter=filter, team=team).run()

    # TODO: Load specified IDs from Postgres model as well

    # if not request.user.is_authenticated:  # for mypy
    #     raise exceptions.NotAuthenticated()
    # viewed_session_recordings = set(
    #     SessionRecordingViewed.objects.filter(team=team, user=request.user).values_list("session_id", flat=True)
    # )

    # distinct_ids = map(lambda x: x["distinct_id"], ch_session_recordings)
    # person_distinct_ids = PersonDistinctId.objects.filter(distinct_id__in=distinct_ids, team=team).select_related(
    #     "person"
    # )
    # distinct_id_to_person = {}
    # for person_distinct_id in person_distinct_ids:
    #     distinct_id_to_person[person_distinct_id.distinct_id] = person_distinct_id.person

    # Convert clickhouse recordings to Django models
    recordings = SessionRecording.get_or_build_from_clickhouse(team, ch_session_recordings)
    remaining_session_ids = (
        set(filter.session_ids) - set(map(lambda x: x.session_id, recordings)) if filter.session_ids else set()
    )

    # If we have a list of session ids, we need to load the rest of the recordings from Postgres as well
    if remaining_session_ids:
        persisted_recordings = SessionRecording.objects.filter(session_id__in=remaining_session_ids, team=team).all()
        recordings = recordings + list(persisted_recordings)

    session_recording_serializer = SessionRecordingSerializer(recordings, many=True)
    results = session_recording_serializer.data

    return {"results": results, "has_next": more_recordings_available}
