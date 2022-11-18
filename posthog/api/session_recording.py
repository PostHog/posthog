import dataclasses
import json
from datetime import datetime
from typing import Any, List, Optional, Union

from dateutil import parser
from rest_framework import exceptions, request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.person import PersonSerializer
from posthog.api.routing import StructuredViewSetMixin
from posthog.models import Filter, PersonDistinctId, SessionRecordingPlaylist, SessionRecordingPlaylistItem
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.person import Person
from posthog.models.session_recording_event import SessionRecordingViewed
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
    playlists = serializers.ListField()


class SessionRecordingWithPlaylistsSerializer(serializers.Serializer):
    id = serializers.CharField()
    playlists = serializers.ListField()


class SessionRecordingSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    viewed = serializers.BooleanField()
    duration = serializers.DurationField()
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    distinct_id = serializers.CharField()
    properties = serializers.DictField(required=False)
    matching_events = serializers.ListField(required=False)

    def to_representation(self, instance):
        return {
            "id": instance["session_id"],
            "viewed": instance["viewed"],
            "recording_duration": instance.get("duration"),
            "start_time": instance["start_time"],
            "end_time": instance["end_time"],
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

    def _get_session_recording_list(self, filter):
        return SessionRecordingList(filter=filter, team=self.team).run()

    def _get_session_recording_list_properties(self, filter, session_ids: List[str]):
        return SessionRecordingProperties(team=self.team, filter=filter, session_ids=session_ids).run()

    def _get_session_recording_snapshots(
        self, request, session_recording_id, limit, offset, recording_start_time: Optional[datetime]
    ):
        return SessionRecording(
            request=request,
            team=self.team,
            session_recording_id=session_recording_id,
            recording_start_time=recording_start_time,
        ).get_snapshots(limit, offset)

    def _get_session_recording_meta_data(self, request, session_recording_id, recording_start_time: Optional[datetime]):
        return SessionRecording(
            request=request,
            team=self.team,
            session_recording_id=session_recording_id,
            recording_start_time=recording_start_time,
        ).get_metadata()

    def _update_recording_playlists(
        self, playlist_ids: List[str], session_id: str, recording_start_time: Optional[datetime]
    ) -> List[str]:
        session_recording = SessionRecording(
            request=request,
            team=self.team,
            session_recording_id=session_id,
            recording_start_time=recording_start_time,
        )

        if not session_recording.query_session_exists():
            raise exceptions.NotFound("Session not found")

        old_playlist_ids = [
            item.playlist_id
            for item in SessionRecordingPlaylistItem.objects.filter(session_id=session_id).exclude(deleted=True).all()
        ]
        new_playlist_ids = [
            playlist.id
            for playlist in SessionRecordingPlaylist.objects.filter(id__in=playlist_ids).exclude(deleted=True).all()
        ]
        ids_to_add = [id for id in new_playlist_ids if id not in old_playlist_ids]
        ids_to_remove = [id for id in old_playlist_ids if id not in new_playlist_ids]

        candidate_playlists = SessionRecordingPlaylist.objects.filter(id__in=ids_to_add).exclude(deleted=True)

        # Determine which records to update and which to create
        records = []
        records_to_create = []
        records_to_update = []

        for playlist in candidate_playlists:
            existing_playlist_item = SessionRecordingPlaylistItem.objects.filter(
                playlist=playlist, session_id=session_id
            ).first()

            existing_playlist_item_id = None
            if existing_playlist_item is not None:
                existing_playlist_item_id = existing_playlist_item.id

            records.append(
                {
                    "id": existing_playlist_item_id,
                    "playlist": playlist,
                }
            )

        [
            records_to_update.append(record) if record["id"] is not None else records_to_create.append(record)
            for record in records
        ]
        [record.pop("id") for record in records_to_create]

        SessionRecordingPlaylistItem.objects.bulk_create(
            [
                SessionRecordingPlaylistItem(session_id=session_id, playlist=values.get("playlist"))
                for values in records_to_create
            ]
        )
        SessionRecordingPlaylistItem.objects.bulk_update(
            [SessionRecordingPlaylistItem(id=values.get("id"), deleted=False) for values in records_to_update],
            ["deleted"],
            batch_size=500,
        )

        if ids_to_remove:
            SessionRecordingPlaylistItem.objects.filter(playlist_id__in=ids_to_remove, session_id=session_id).update(
                deleted=True
            )

        return (
            SessionRecordingPlaylistItem.objects.filter(session_id=session_id)
            .exclude(deleted=True)
            .values_list("id", flat=True)
        )

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
            map(lambda x: {**x, "viewed": x["session_id"] in viewed_session_recordings}, session_recordings)
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
        recording_start_time_string = request.GET.get("recording_start_time")
        recording_start_time = parser.parse(recording_start_time_string) if recording_start_time_string else None

        session_recording_meta_data = self._get_session_recording_meta_data(
            request, session_recording_id, recording_start_time
        )
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
                "playlists": session_recording_meta_data.playlists,
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
                    "person": PersonSerializer(instance=person).data if person else None,
                }
            }
        )

    # As of now, you can only "update" a session recording by adding or removing a recording from a static playlist
    def patch(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        session_id = kwargs["pk"]
        playlist_ids = request.data.get("playlists", None)
        recording_start_time_string = request.GET.get("recording_start_time")
        recording_start_time = parser.parse(recording_start_time_string) if recording_start_time_string else None

        if not request.user.is_authenticated:  # for mypy
            raise exceptions.NotAuthenticated()

        new_playlist_ids = []
        if playlist_ids is not None:
            new_playlist_ids = self._update_recording_playlists(playlist_ids, session_id, recording_start_time)

        session_recording_serializer = SessionRecordingWithPlaylistsSerializer(
            data={
                "id": session_id,
                "playlists": new_playlist_ids,
            }
        )

        session_recording_serializer.is_valid(raise_exception=True)

        return response.Response({"result": {"session_recording": session_recording_serializer.data}})

    # Paginated endpoint that returns the snapshots for the recording
    @action(methods=["GET"], detail=True)
    def snapshots(self, request: request.Request, **kwargs):
        session_recording_id = kwargs["pk"]
        filter = Filter(request=request)
        limit = filter.limit if filter.limit else DEFAULT_RECORDING_CHUNK_LIMIT
        offset = filter.offset if filter.offset else 0
        recording_start_time_string = request.GET.get("recording_start_time")
        recording_start_time = parser.parse(recording_start_time_string) if recording_start_time_string else None

        session_recording_snapshot_data = self._get_session_recording_snapshots(
            request, session_recording_id, limit, offset, recording_start_time
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

    # Returns properties given a list of session recording ids
    @action(methods=["GET"], detail=False)
    def properties(self, request: request.Request, **kwargs):
        filter = SessionRecordingsFilter(request=request)
        session_ids = [
            recording_id for recording_id in json.loads(self.request.GET.get("session_ids", "[]")) if recording_id
        ]
        session_recordings_properties = self._get_session_recording_list_properties(filter, session_ids)

        if not request.user.is_authenticated:  # for mypy
            raise exceptions.NotAuthenticated()

        session_recording_serializer = SessionRecordingPropertiesSerializer(
            data=session_recordings_properties, many=True
        )

        session_recording_serializer.is_valid(raise_exception=True)

        return Response({"results": session_recording_serializer.data})
