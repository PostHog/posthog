import dataclasses
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Union

from rest_framework import exceptions, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.person import PersonSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.helpers.session_recording import (
    DecompressedRecordingData,
    RecordingEventSummary,
    SnapshotData,
    WindowId,
    get_metadata_from_event_summaries,
)
from posthog.models import Filter, PersonDistinctId
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.person import Person
from posthog.models.session_recording_event import SessionRecordingViewed
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.queries.session_recordings.session_recording import RecordingMetadata, SessionRecording
from posthog.queries.session_recordings.session_recording_list import SessionRecordingList
from posthog.storage.object_storage import list_all_objects, read, read_all
from posthog.utils import format_query_params_absolute_url, should_read_recordings_from_object_storage

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
        return SessionRecordingList(filter=filter, team=self.team).run()

    def _read_and_combine_object_storage_files(self, folder, limit=None, offset=None):
        files = list_all_objects(folder)
        has_next = False
        if limit is not None:
            has_next = len(files) > limit + offset
            files = files[offset : offset + limit]

        file_names = [object["Key"] for object in files]

        file_contents = read_all(file_names)
        rows = [
            event_summary_string
            for _, metadata_string in file_contents
            for event_summary_string in metadata_string.split("\n")
        ]
        combined_json_string = "[" + ",".join(rows) + "]"
        combined_data = json.loads(combined_json_string)
        return combined_data, has_next

    def _get_session_recording_snapshots_from_object_storage(
        self, session_recording_id, limit, offset
    ) -> DecompressedRecordingData:
        session_data_folder = f"session_recordings/team_id/{self.team_id}/session_id/{session_recording_id}/data/"
        session_data, has_next = self._read_and_combine_object_storage_files(session_data_folder, limit, offset)
        snapshot_data_by_window_id: Dict[WindowId, List[SnapshotData]] = defaultdict(list)

        for snapshot_data in session_data:
            snapshot_data_by_window_id[snapshot_data.get("$window_id", "")].append(snapshot_data)

        return DecompressedRecordingData(has_next=has_next, snapshot_data_by_window_id=snapshot_data_by_window_id)

    def _get_session_recording_snapshots(self, request, session_recording_id, limit, offset):

        if should_read_recordings_from_object_storage(self.team_id):
            return self._get_session_recording_snapshots_from_object_storage(session_recording_id, limit, offset)
        return SessionRecording(
            request=request, team=self.team, session_recording_id=session_recording_id
        ).get_snapshots(limit, offset)

    def _get_session_recording_metadata_from_object_storage(self, session_recording_id):
        base_folder = f"session_recordings/team_id/{self.team_id}/session_id/{session_recording_id}/metadata/"
        metadata_file = f"{base_folder}metadata.json"
        metadata_file_content = read(metadata_file)
        distinct_id = json.loads(metadata_file_content).get("distinctId")

        event_summaries, _ = self._read_and_combine_object_storage_files(f"{base_folder}event_summaries/")

        parsed_event_summaries: List[RecordingEventSummary] = [
            RecordingEventSummary(
                timestamp=datetime.fromtimestamp(event_summary.get("timestamp", 0) / 1000, timezone.utc),
                window_id=event_summary.get("windowId", ""),
                type=event_summary.get("type"),
                source=event_summary.get("source"),
            )
            for event_summary in event_summaries
        ]

        segments, start_and_end_times_by_window_id = get_metadata_from_event_summaries(parsed_event_summaries)

        return RecordingMetadata(
            segments=segments,
            start_and_end_times_by_window_id=start_and_end_times_by_window_id,
            distinct_id=distinct_id,
        )

    def _get_session_recording_meta_data(self, request, session_recording_id):
        if should_read_recordings_from_object_storage(self.team_id):
            return self._get_session_recording_metadata_from_object_storage(session_recording_id)
        return SessionRecording(
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
            ) if session_recording_meta_data.distinct_id else None
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

        session_recording_snapshot_data = self._get_session_recording_snapshots(
            request, session_recording_id, limit, offset
        )

        if session_recording_snapshot_data.snapshot_data_by_window_id == {}:
            raise exceptions.NotFound("Snapshots not found")
        next_url = (
            format_query_params_absolute_url(request, offset + limit, limit)
            if session_recording_snapshot_data.has_next
            else None
        )

        return response.Response(
            {
                "result": {
                    "next": next_url,
                    "snapshot_data_by_window_id": session_recording_snapshot_data.snapshot_data_by_window_id,
                }
            }
        )
