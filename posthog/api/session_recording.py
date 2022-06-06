import dataclasses
import json
from itertools import groupby
from typing import Any, Union

from rest_framework import exceptions, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ee.clickhouse.queries.session_recordings.clickhouse_session_recording import ClickhouseSessionRecording
from ee.clickhouse.queries.session_recordings.clickhouse_session_recording_list import ClickhouseSessionRecordingList
from posthog.api.person import PersonSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.models import Filter, PersonDistinctId
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.person import Person
from posthog.models.session_recording_event import SessionRecordingViewed
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.storage.object_storage import storage_client

DEFAULT_RECORDING_CHUNK_LIMIT = 20  # Should be tuned to find the best value


class SessionRecordingMetadataSerializer(serializers.Serializer):
    segments = serializers.ListField(required=False)
    start_and_end_times_by_window_id = serializers.DictField(required=False)
    session_id = serializers.CharField()
    viewed = serializers.BooleanField()


class SessionRecordingSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    viewed = serializers.BooleanField()
    duration = serializers.DurationField()
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    distinct_id = serializers.CharField()

    def to_representation(self, instance):
        return {
            "id": instance["session_id"],
            "viewed": instance["viewed"],
            "recording_duration": instance.get("duration"),
            "start_time": instance["start_time"],
            "end_time": instance["end_time"],
            "distinct_id": instance["distinct_id"],
        }


class SessionRecordingViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

    def _get_session_recording_list(self, filter):
        return ClickhouseSessionRecordingList(filter=filter, team=self.team).run()

    def _get_session_recording_snapshots(self, request, session_recording_id, limit, offset):
        return ClickhouseSessionRecording(
            request=request, team=self.team, session_recording_id=session_recording_id
        ).get_snapshots(limit, offset)

    def _get_session_recording_meta_data(self, request, session_recording_id):
        return ClickhouseSessionRecording(
            request=request, team=self.team, session_recording_id=session_recording_id
        ).get_metadata()

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

        session_recording_meta_data = self._get_session_recording_meta_data(request, session_recording_id)
        if not session_recording_meta_data:
            raise exceptions.NotFound("Session not found")

        if not request.user.is_authenticated:  # for mypy
            raise exceptions.NotAuthenticated()
        viewed_session_recording = SessionRecordingViewed.objects.filter(
            team=self.team, user=request.user, session_id=session_recording_id
        ).exists()

        session_recording_serializer = SessionRecordingMetadataSerializer(
            data={
                "segments": [dataclasses.asdict(segment) for segment in session_recording_meta_data.segments],
                "start_and_end_times_by_window_id": session_recording_meta_data.start_and_end_times_by_window_id,
                "session_id": session_recording_id,
                "viewed": viewed_session_recording,
            }
        )
        session_recording_serializer.is_valid(raise_exception=True)

        try:
            person: Union[Person, None] = Person.objects.get(
                persondistinctid__distinct_id=session_recording_meta_data.distinct_id,
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
                    "person": PersonSerializer(instance=person).data,
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

        # TODO: handle pagination
        # TODO: handle response compression
        # TODO: handle response caching
        store = storage_client()
        assert store is not None
        all_events = []
        for obj in store.list_objects_v2(
            Bucket="posthog",
            Prefix=f"session-recordings/session-recordings/team_id=1/session_id={session_recording_id}/",
        )["Contents"]:
            resp = store.get_object(Bucket="posthog", Key=obj["Key"])
            body = resp["Body"].read()
            for line in body.split(b"\n"):
                if not line:
                    continue
                event_wrapper = json.loads(line)
                all_events += [json.loads(event_wrapper["data"])["data"]["properties"]]

        events_by_window_id = {
            window_id: list(events)
            for window_id, events in groupby(
                sorted(all_events, key=lambda event: event["$window_id"]), lambda event: event["$window_id"]
            )
        }

        def extract_rrweb_events_from_event(event):
            # Some of the earlier events don't have the expected format locally
            # so need to guard against that.
            if isinstance(event["$snapshot_data"]["data"], str):
                # At some point this data was base64 encoded before I removed
                # this encoding, just ignore these. It's just bad data in my dev
                # env.
                return []
            try:
                return event["$snapshot_data"]["data"]
            except KeyError:
                return []

        snapshot_data_by_window_id = {
            window_id: [rrweb_event for event in events for rrweb_event in extract_rrweb_events_from_event(event)]
            for window_id, events in events_by_window_id.items()
        }

        return response.Response({"result": {"next": None, "snapshot_data_by_window_id": snapshot_data_by_window_id}})
