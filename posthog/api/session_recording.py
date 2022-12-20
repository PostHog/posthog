import base64
import json
from typing import Any, Optional

from dateutil import parser
from rest_framework import exceptions, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from posthog.api.person import PersonSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.models import Filter, PersonDistinctId
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.person import Person
from posthog.models.session_recording_event import SessionRecordingViewed
from posthog.models.team.team import Team
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.queries.session_recordings.session_recording import SessionRecording
from posthog.queries.session_recordings.session_recording_list import SessionRecordingList
from posthog.queries.session_recordings.session_recording_properties import SessionRecordingProperties
from posthog.rate_limit import PassThroughClickHouseBurstRateThrottle, PassThroughClickHouseSustainedRateThrottle
from posthog.utils import format_query_params_absolute_url

DEFAULT_RECORDING_CHUNK_LIMIT = 20  # Should be tuned to find the best value


class SessionRecordingMetadataSerializer(serializers.Serializer):
    segments = serializers.ListField(required=False)
    start_and_end_times_by_window_id = serializers.DictField(required=False)
    session_id = serializers.CharField()
    viewed = serializers.BooleanField()


class SessionRecordingSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    viewed = serializers.BooleanField()
    distinct_id = serializers.CharField()
    duration = serializers.DurationField()
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    click_count = serializers.IntegerField(required=False)
    keypress_count = serializers.IntegerField(required=False)
    urls = serializers.ListField(required=False)
    distinct_id = serializers.CharField()
    matching_events = serializers.ListField(required=False)

    def to_representation(self, instance):
        return {
            "id": instance["session_id"],
            "viewed": instance["viewed"],
            "distinct_id": instance["distinct_id"],
            "recording_duration": instance.get("duration"),
            "start_time": instance["start_time"],
            "end_time": instance["end_time"],
            "click_count": instance["click_count"],
            "keypress_count": instance["keypress_count"],
            "urls": instance.get("urls"),
            "distinct_id": instance["distinct_id"],
            "matching_events": instance["matching_events"],
        }


class SessionRecordingPropertiesSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    properties = serializers.DictField(required=False)

    def to_representation(self, instance):
        return {
            "id": instance["session_id"],
            "properties": instance["properties"],
        }


class SessionRecordingViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
    throttle_classes = [PassThroughClickHouseBurstRateThrottle, PassThroughClickHouseSustainedRateThrottle]

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        filter = SessionRecordingsFilter(request=request)
        return Response(list_recordings(filter, request, self.team))

    # Returns meta data about the recording
    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        session_recording_id = kwargs["pk"]
        recording_start_time_string = request.GET.get("recording_start_time")
        recording_start_time = parser.parse(recording_start_time_string) if recording_start_time_string else None

        session_recording_meta_data = SessionRecording(
            request=request,
            team=self.team,
            session_recording_id=session_recording_id,
            recording_start_time=recording_start_time,
        ).get_metadata()

        if not session_recording_meta_data:
            raise exceptions.NotFound("Session not found")

        if not request.user.is_authenticated:  # for mypy
            raise exceptions.NotAuthenticated()
        viewed_session_recording = SessionRecordingViewed.objects.filter(
            team=self.team, user=request.user, session_id=session_recording_id
        ).exists()

        session_recording_serializer = SessionRecordingMetadataSerializer(
            data={
                "segments": session_recording_meta_data["segments"],
                "start_and_end_times_by_window_id": session_recording_meta_data["start_and_end_times_by_window_id"],
                "session_id": session_recording_id,
                "viewed": viewed_session_recording,
            }
        )
        session_recording_serializer.is_valid(raise_exception=True)

        try:
            person: Optional[Person] = Person.objects.get(
                persondistinctid__distinct_id=session_recording_meta_data["distinct_id"],
                persondistinctid__team_id=self.team,
                team=self.team,
            )
        except Person.DoesNotExist:
            person = None

        if request.GET.get("save_view"):
            SessionRecordingViewed.objects.get_or_create(
                team=self.team, user=request.user, session_id=session_recording_id
            )

        return response.Response(
            {
                "result": {
                    "session_recording": session_recording_serializer.data,
                    "person": PersonSerializer(instance=person).data if person else None,
                }
            }
        )

    # Paginated endpoint that returns the snapshots for the recording
    @action(methods=["GET"], detail=True)
    def snapshots(self, request: request.Request, **kwargs):
        session_recording_id = kwargs["pk"]
        filter = Filter(request=request)
        limit = filter.limit if filter.limit else DEFAULT_RECORDING_CHUNK_LIMIT
        offset = filter.offset if filter.offset else 0
        recording_start_time_string = request.GET.get("recording_start_time")
        recording_start_time = parser.parse(recording_start_time_string) if recording_start_time_string else None

        session_recording_snapshot_data = SessionRecording(
            request=request,
            team=self.team,
            session_recording_id=session_recording_id,
            recording_start_time=recording_start_time,
        ).get_snapshots(limit, offset)

        if session_recording_snapshot_data["snapshot_data_by_window_id"] == {}:
            raise exceptions.NotFound("Snapshots not found")

        next_url = (
            format_query_params_absolute_url(request, offset + limit, limit)
            if session_recording_snapshot_data["has_next"]
            else None
        )

        # NOTE: This is debug code to try and see what is going on for very specific failures due to unicode errors
        try:
            JSONRenderer().render(data=session_recording_snapshot_data["snapshot_data_by_window_id"])
        except Exception as e:
            return response.Response(
                {
                    "error": "Unicode error when decoding snapshot data",
                    "detail": str(e),
                    "base64_content": base64.b64encode(
                        json.dumps(session_recording_snapshot_data["snapshot_data_by_window_id"]).encode("utf-8")
                    ),
                },
                status=400,
            )

        return response.Response(
            {
                "result": {
                    "next": next_url,
                    "snapshot_data_by_window_id": session_recording_snapshot_data["snapshot_data_by_window_id"],
                }
            }
        )

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
    (session_recordings, more_recordings_available) = SessionRecordingList(filter=filter, team=team).run()

    if not request.user.is_authenticated:  # for mypy
        raise exceptions.NotAuthenticated()
    viewed_session_recordings = set(
        SessionRecordingViewed.objects.filter(team=team, user=request.user).values_list("session_id", flat=True)
    )

    distinct_ids = map(lambda x: x["distinct_id"], session_recordings)
    person_distinct_ids = PersonDistinctId.objects.filter(distinct_id__in=distinct_ids, team=team).select_related(
        "person"
    )
    distinct_id_to_person = {}
    for person_distinct_id in person_distinct_ids:
        distinct_id_to_person[person_distinct_id.distinct_id] = person_distinct_id.person

    session_recordings = list(
        map(lambda x: {**x, "viewed": x["session_id"] in viewed_session_recordings}, session_recordings)
    )

    session_recording_serializer = SessionRecordingSerializer(data=session_recordings, many=True)
    session_recording_serializer.is_valid(raise_exception=True)
    results = list(
        map(
            lambda session_recording: {
                **session_recording,
                "person": PersonSerializer(instance=distinct_id_to_person.get(session_recording["distinct_id"])).data,
            },
            session_recording_serializer.data,
        )
    )

    return {"results": results, "has_next": more_recordings_available}
