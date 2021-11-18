from typing import Any, Union

from rest_framework import exceptions, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.person import PersonSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.models import PersonDistinctId
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.person import Person
from posthog.models.session_recording_event import SessionRecordingViewed
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.queries.session_recordings.session_recording import SessionRecording
from posthog.queries.session_recordings.session_recording_list import SessionRecordingList


class SessionRecordingSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    viewed = serializers.BooleanField()
    duration = serializers.DurationField()
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    distinct_id = serializers.CharField()
    active_segments_by_window_id = serializers.DictField(required=False)

    def to_representation(self, instance):
        return {
            "id": instance["session_id"],
            "viewed": instance["viewed"],
            "recording_duration": instance.get("duration"),
            "start_time": instance["start_time"],
            "end_time": instance["end_time"],
            "distinct_id": instance["distinct_id"],
            "active_segments_by_window_id": instance.get("active_segments_by_window_id"),
        }


class SessionRecordingViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

    def _get_session_recording_list(self, filter):
        return SessionRecordingList(filter=filter, team_id=self.team.pk).run()

    def _get_session_recording_snapshots(self, request, filter, session_recording_id):
        return SessionRecording(
            request=request, filter=filter, team=self.team, session_recording_id=session_recording_id
        ).get_snapshots()

    def _get_session_recording_meta_data(self, request, filter, session_recording_id, include_active_segments):
        return SessionRecording(
            request=request, filter=filter, team=self.team, session_recording_id=session_recording_id
        ).get_metadata(include_active_segments=include_active_segments)

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        filter = SessionRecordingsFilter(request=request)
        (session_recordings, more_recordings_available) = self._get_session_recording_list(filter)

        if not request.user.is_authenticated:  # for mypy
            raise exceptions.NotAuthenticated()
        viewed_session_recordings = set(
            SessionRecordingViewed.objects.filter(team=self.team, user=request.user).values_list(
                "session_id", flat=True
            )
        )

        distinct_ids = map(lambda x: x["distinct_id"], session_recordings)
        person_distinct_ids = PersonDistinctId.objects.filter(
            distinct_id__in=distinct_ids, team=self.team
        ).select_related("person")
        distinct_id_to_person = {}
        for person_distinct_id in person_distinct_ids:
            distinct_id_to_person[person_distinct_id.distinct_id] = person_distinct_id.person

        session_recordings = list(
            map(lambda x: {**x, "viewed": x["session_id"] in viewed_session_recordings,}, session_recordings,)
        )

        session_recording_serializer = SessionRecordingSerializer(data=session_recordings, many=True)

        session_recording_serializer.is_valid(raise_exception=True)

        session_recording_serializer_with_person = list(
            map(
                lambda session_recording: {
                    **session_recording,
                    "person": PersonSerializer(
                        instance=distinct_id_to_person.get(session_recording["distinct_id"])
                    ).data,
                },
                session_recording_serializer.data,
            )
        )

        return Response({"results": session_recording_serializer_with_person, "has_next": more_recordings_available})

    # Returns meta data about the recording
    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        session_recording_id = kwargs["pk"]
        filter = SessionRecordingsFilter(request=request)

        include_active_segments = (
            True if request.query_params.get("include_active_segments", "false").lower() == "true" else False
        )

        session_recording_meta_data = self._get_session_recording_meta_data(
            request, filter, session_recording_id, include_active_segments
        )
        if not session_recording_meta_data.get("session_id"):
            raise exceptions.NotFound("Session not found")

        if not request.user.is_authenticated:  # for mypy
            raise exceptions.NotAuthenticated()
        viewed_session_recording = SessionRecordingViewed.objects.filter(
            team=self.team, user=request.user, session_id=session_recording_id
        ).exists()

        session_recording_serializer = SessionRecordingSerializer(
            data={**session_recording_meta_data, "session_id": session_recording_id, "viewed": viewed_session_recording}
        )
        session_recording_serializer.is_valid(raise_exception=True)

        distinct_id = session_recording_meta_data["distinct_id"]

        try:
            person: Union[Person, None] = Person.objects.get(
                persondistinctid__distinct_id=distinct_id, persondistinctid__team_id=self.team, team=self.team
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
                    "person": PersonSerializer(instance=person).data,
                }
            }
        )

    # Paginated endpoint that returns the snapshots for the recording
    @action(methods=["GET"], detail=True)
    def snapshots(self, request: request.Request, **kwargs):
        session_recording_id = kwargs["pk"]
        filter = SessionRecordingsFilter(request=request)
        session_recording_snapshots = self._get_session_recording_snapshots(request, filter, session_recording_id)
        if len(session_recording_snapshots["snapshots"]) == 0:
            raise exceptions.NotFound("Snapshots not found")
        return response.Response({"result": session_recording_snapshots})
