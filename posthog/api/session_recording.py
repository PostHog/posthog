from typing import Any

from rest_framework import exceptions, request, response, serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.person import PersonDistinctId
from posthog.models.session_recording_event import SessionRecordingViewed
from posthog.permissions import ProjectMembershipNecessaryPermissions
from posthog.queries.session_recordings.session_recording import SessionRecording
from posthog.queries.session_recordings.session_recording_list import SessionRecordingList


class SessionRecordingSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    viewed = serializers.BooleanField()
    duration = serializers.DurationField()
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    distinct_id = serializers.CharField()
    email = serializers.CharField(required=False, allow_null=True)

    def to_representation(self, instance):
        to_return = {
            "id": instance["session_id"],
            "viewed": instance["viewed"],
            "recording_duration": instance.get("duration"),
            "start_time": instance["start_time"],
            "end_time": instance["end_time"],
            "distinct_id": instance["distinct_id"],
            "email": instance["email"],
        }
        return to_return


class SessionRecordingViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions]

    def _get_session_recording_list(self, filter):
        return SessionRecordingList(filter=filter, team=self.team).run()

    def _get_session_recording(self, session_recording_id):
        return SessionRecording(team=self.team, session_recording_id=session_recording_id).run()

    def list(self, request: request.Request, *args: Any, **kwargs: Any) -> Response:
        filter = SessionRecordingsFilter(request=request)
        session_recordings = self._get_session_recording_list(filter)

        distinct_ids = map(lambda x: x["distinct_id"], session_recordings)
        person_distinct_ids = PersonDistinctId.objects.filter(
            distinct_id__in=distinct_ids, team=self.team
        ).select_related("person")
        distinct_id_to_email = {}
        for person_distinct_id in person_distinct_ids:
            distinct_id_to_email[person_distinct_id.distinct_id] = person_distinct_id.person.properties.get("email")

        if not request.user.is_authenticated:  # for mypy
            raise exceptions.NotAuthenticated()
        viewed_session_recordings = set(
            SessionRecordingViewed.objects.filter(team=self.team, user=request.user).values_list(
                "session_id", flat=True
            )
        )

        session_recordings = list(
            map(
                lambda x: {
                    **x,
                    "email": distinct_id_to_email.get(x["distinct_id"]),
                    "viewed": x["session_id"] in viewed_session_recordings,
                },
                session_recordings,
            )
        )

        serializer = SessionRecordingSerializer(data=session_recordings, many=True)
        serializer.is_valid(raise_exception=True)

        return Response({"results": serializer.data})

    def retrieve(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        session_recording_id = kwargs["pk"]
        session_recording = self._get_session_recording(session_recording_id)
        if len(session_recording.get("snapshots", [])) == 0:
            raise exceptions.NotFound()

        if request.GET.get("save_view"):
            SessionRecordingViewed.objects.get_or_create(
                team=self.team, user=request.user, session_id=session_recording_id
            )

        return response.Response({"result": session_recording})
