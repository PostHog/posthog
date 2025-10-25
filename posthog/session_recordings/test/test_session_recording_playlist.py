import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, QueryMatchingTest, snapshot_postgres_queries
from unittest import mock
from unittest.mock import MagicMock, patch

from django.db import transaction
from django.test import override_settings

from boto3 import resource
from botocore.config import Config
from parameterized import parameterized
from rest_framework import status

from posthog import redis
from posthog.models import SessionRecording, SessionRecordingPlaylistItem, Team
from posthog.models.file_system.file_system import FileSystem
from posthog.models.user import User
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.session_recordings.models.session_recording_playlist import (
    SessionRecordingPlaylist,
    SessionRecordingPlaylistViewed,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.session_recording_playlist_api import PLAYLIST_COUNT_REDIS_PREFIX
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)

TEST_BUCKET = "test_storage_bucket-ee.TestSessionRecordingPlaylist"


@override_settings(
    OBJECT_STORAGE_SESSION_RECORDING_BLOB_INGESTION_FOLDER=TEST_BUCKET,
    OBJECT_STORAGE_SESSION_RECORDING_LTS_FOLDER=f"{TEST_BUCKET}_lts",
)
class TestSessionRecordingPlaylist(APIBaseTest, QueryMatchingTest):
    def teardown_method(self, method) -> None:
        s3 = resource(
            "s3",
            endpoint_url=OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
        bucket = s3.Bucket(OBJECT_STORAGE_BUCKET)
        bucket.objects.filter(Prefix=TEST_BUCKET).delete()

    def _create_playlist(
        self,
        data: dict | None = None,
        expected_status_code: int | None = None,
        expected_response_json: dict | None = None,
    ):
        post_response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists",
            data=data,
        )

        if expected_status_code:
            assert post_response.status_code == expected_status_code
        else:
            assert post_response.status_code == status.HTTP_201_CREATED

        if expected_response_json:
            assert post_response.json() == expected_response_json

        return post_response

    def _get_non_synthetic_playlists(self, query_params: str = "", expected_synthetic_count: int = 6) -> list[dict]:
        url = f"/api/projects/{self.team.id}/session_recording_playlists{query_params}"
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

        results = response.json()["results"]
        synthetic_results = [p for p in results if p.get("is_synthetic")]
        non_synthetic_results = [p for p in results if not p.get("is_synthetic")]

        assert len(synthetic_results) == expected_synthetic_count

        return non_synthetic_results

    def test_list_playlists_when_there_are_no_playlists(self):
        response = self.client.get(f"/api/projects/{self.team.id}/session_recording_playlists")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]

        # When there are no user-created playlists, we should only get synthetic playlists
        assert len(results) > 0, "Should have synthetic playlists"
        assert all(p.get("is_synthetic") for p in results), "All playlists should be synthetic"

    def test_list_playlists_when_there_are_some_playlists(self):
        playlist_one = self._create_playlist({"name": "test", "type": "collection"})
        playlist_two = self._create_playlist({"name": "test2", "type": "collection"})

        # set some saved filter counts up
        SessionRecordingViewed.objects.create(
            team=self.team,
            user=self.user,
            session_id="a",
        )
        redis.get_client().set(
            f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist_two.json()['short_id']}",
            json.dumps({"session_ids": ["a", "b"], "has_more": False, "previous_ids": ["b"]}),
        )

        response = self.client.get(f"/api/projects/{self.team.id}/session_recording_playlists")

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert response_data["count"] == 8
        assert response_data["next"] is None
        assert response_data["previous"] is None
        assert [x for x in response_data["results"] if not x["is_synthetic"]] == [
            {
                "is_synthetic": False,
                "created_at": mock.ANY,
                "created_by": {
                    "distinct_id": self.user.distinct_id,
                    "email": self.user.email,
                    "first_name": "",
                    "hedgehog_config": None,
                    "id": self.user.id,
                    "is_email_verified": None,
                    "last_name": "",
                    "role_at_organization": None,
                    "uuid": mock.ANY,
                },
                "deleted": False,
                "derived_name": None,
                "description": "",
                "filters": {},
                "id": playlist_two.json()["id"],
                "last_modified_at": mock.ANY,
                "last_modified_by": {
                    "distinct_id": self.user.distinct_id,
                    "email": self.user.email,
                    "first_name": "",
                    "hedgehog_config": None,
                    "id": self.user.id,
                    "is_email_verified": None,
                    "last_name": "",
                    "role_at_organization": None,
                    "uuid": mock.ANY,
                },
                "name": "test2",
                "pinned": False,
                "recordings_counts": {
                    "collection": {
                        "count": None,
                        "watched_count": 0,
                    },
                    "saved_filters": {
                        "count": 2,
                        "has_more": False,
                        "watched_count": 1,
                        "increased": True,
                        "last_refreshed_at": None,
                    },
                },
                "short_id": playlist_two.json()["short_id"],
                "type": "collection",
            },
            {
                "is_synthetic": False,
                "created_at": mock.ANY,
                "created_by": {
                    "distinct_id": self.user.distinct_id,
                    "email": self.user.email,
                    "first_name": "",
                    "hedgehog_config": None,
                    "id": self.user.id,
                    "is_email_verified": None,
                    "last_name": "",
                    "role_at_organization": None,
                    "uuid": mock.ANY,
                },
                "deleted": False,
                "derived_name": None,
                "description": "",
                "filters": {},
                "id": playlist_one.json()["id"],
                "last_modified_at": mock.ANY,
                "last_modified_by": {
                    "distinct_id": self.user.distinct_id,
                    "email": self.user.email,
                    "first_name": "",
                    "hedgehog_config": None,
                    "id": self.user.id,
                    "is_email_verified": None,
                    "last_name": "",
                    "role_at_organization": None,
                    "uuid": mock.ANY,
                },
                "name": "test",
                "pinned": False,
                "recordings_counts": {
                    "collection": {
                        "count": None,
                        "watched_count": 0,
                    },
                    "saved_filters": {
                        "count": None,
                        "has_more": None,
                        "watched_count": None,
                        "increased": None,
                        "last_refreshed_at": None,
                    },
                },
                "short_id": playlist_one.json()["short_id"],
                "type": "collection",
            },
        ]

    @parameterized.expand(
        [
            ["without_type", {"name": "test"}],
            ["with_unknown_type", {"name": "test", "type": "tomato"}],
        ]
    )
    def test_rejects_invalid_playlist_type(self, _name: str, playlist_data: dict) -> None:
        self._create_playlist(
            playlist_data,
            status.HTTP_400_BAD_REQUEST,
            expected_response_json={
                "attr": None,
                "code": "invalid_input",
                "detail": "Must provide a valid playlist type: either filters or collection",
                "type": "validation_error",
            },
        )

    @parameterized.expand(
        [
            [
                "filters",
                {"name": "test filters", "type": "filters", "filters": {"foo": "bar"}},
                "filters",
            ],
            [
                "collection",
                {"name": "test collection", "type": "collection"},
                "collection",
            ],
        ]
    )
    def test_creates_playlist_with_type(self, _name: str, playlist_data: dict, expected_type: str) -> None:
        response = self._create_playlist(playlist_data)

        playlist_id = response.json()["id"]
        playlist = SessionRecordingPlaylist.objects.get(id=playlist_id)
        assert playlist.type == expected_type

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["name"] == playlist_data["name"]
        assert response.json()["type"] == expected_type

    @parameterized.expand(
        [
            [
                "saved_filters_with_no_filters",
                {"type": "filters"},
                "You must provide a valid filters when creating a saved filter",
            ],
            [
                "collection_with_filters",
                {"type": "collection", "filters": {"events": [{"id": "test"}]}},
                "You cannot create a collection with filters",
            ],
        ]
    )
    def test_rejects_invalid_filter_combinations(self, _name: str, playlist_data: dict, expected_error: str) -> None:
        self._create_playlist(
            playlist_data,
            status.HTTP_400_BAD_REQUEST,
            expected_response_json={
                "attr": None,
                "code": "invalid_input",
                "detail": expected_error,
                "type": "validation_error",
            },
        )

    def test_can_create_many_playlists_without_n_plus_1(self):
        # one query to get started and then 14 per creation (was 13, +1 for organization query)
        with self.assertNumQueries(14 * 50 + 1):
            for i in range(50):
                self._create_playlist({"name": f"test-{i}", "type": "collection"})

        # 14 per creation (was 13, +1 for organization query)
        with self.assertNumQueries(14 * 100):
            for i in range(100):
                self._create_playlist({"name": f"test-{i}", "type": "collection"})

    def test_gets_individual_playlist_by_shortid(self):
        create_response = self._create_playlist({"type": "collection"})

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{create_response.json()['short_id']}"
        )

        assert response.json()["short_id"] == create_response.json()["short_id"]

    def test_marks_playlist_as_viewed(self):
        create_response = self._create_playlist({"filters": {"events": [{"id": "test"}]}, "type": "filters"})
        short_id = create_response.json()["short_id"]

        assert SessionRecordingPlaylistViewed.objects.count() == 0

        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}/playlist_viewed"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert SessionRecordingPlaylistViewed.objects.count() == 1
        viewed_record = SessionRecordingPlaylistViewed.objects.first()
        assert viewed_record is not None

        assert viewed_record.playlist_id == create_response.json()["id"]
        assert viewed_record.user_id == self.user.id
        assert viewed_record.team_id == self.team.id
        assert viewed_record.viewed_at == mock.ANY

    def test_can_marks_playlist_as_viewed_more_than_once(self):
        create_response = self._create_playlist({"filters": {"events": [{"id": "test"}]}, "type": "filters"})
        short_id = create_response.json()["short_id"]

        assert SessionRecordingPlaylistViewed.objects.count() == 0

        response_one = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}/playlist_viewed"
        )
        assert response_one.status_code == status.HTTP_200_OK
        response_two = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}/playlist_viewed"
        )
        assert response_two.status_code == status.HTTP_200_OK
        assert SessionRecordingPlaylistViewed.objects.count() == 2

    def test_cannot_mark_playlist_as_viewed_more_than_once_at_the_same_time(self):
        create_response = self._create_playlist({"filters": {"events": [{"id": "test"}]}, "type": "filters"})
        short_id = create_response.json()["short_id"]

        assert SessionRecordingPlaylistViewed.objects.count() == 0

        with freeze_time("2022-01-02"):
            response_one = self.client.post(
                f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}/playlist_viewed"
            )
            assert response_one.status_code == status.HTTP_200_OK
            assert SessionRecordingPlaylistViewed.objects.count() == 1

            # Run the API call in a separate atomic block so it doesn't break the main test transaction
            with transaction.atomic():
                response_two = self.client.post(
                    f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}/playlist_viewed"
                )
                assert response_two.status_code == status.HTTP_200_OK

        assert SessionRecordingPlaylistViewed.objects.count() == 1

    def test_cannot_mark_playlist_as_viewed_in_different_team(self):
        create_response = self._create_playlist({"filters": {"events": [{"id": "test"}]}, "type": "filters"})
        short_id = create_response.json()["short_id"]

        another_team = Team.objects.create(organization=self.organization)

        response = self.client.post(
            f"/api/projects/{another_team.id}/session_recording_playlists/{short_id}/playlist_viewed"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert SessionRecordingPlaylistViewed.objects.count() == 0

    def test_updates_playlist(self):
        create_response = self._create_playlist(
            {
                "type": "filters",
                "filters": {"events": [{"id": "original"}]},
            }
        )
        assert "short_id" in create_response.json(), create_response.json()
        short_id = create_response.json()["short_id"]

        with freeze_time("2022-01-02"):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}",
                {
                    "name": "changed name",
                    "description": "changed description",
                    "filters": {"events": [{"id": "updated"}]},
                    "pinned": True,
                },
            )
            assert response.status_code == status.HTTP_200_OK, response.json()

        assert response.json()["short_id"] == short_id
        assert response.json()["name"] == "changed name"
        assert response.json()["description"] == "changed description"
        assert response.json()["filters"] == {"events": [{"id": "updated"}]}
        assert response.json()["created_at"] == mock.ANY
        assert response.json()["last_modified_at"] == "2022-01-02T00:00:00Z"

    def test_cannot_update_type(self) -> None:
        create_response = self._create_playlist({"type": "collection"})
        assert "short_id" in create_response.json(), create_response.json()
        short_id = create_response.json()["short_id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}",
            {
                "type": "filters",
                "filters": {"events": [{"id": "test"}]},
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    @parameterized.expand([["empty_dict", {}], ["none", None]])
    def test_cannot_update_saved_filter_to_have_no_filters(self, _name: str, updated_filters: dict | None) -> None:
        create_response = self._create_playlist(
            {
                "type": "filters",
                "filters": {"events": [{"id": "test"}]},
            }
        )
        assert "short_id" in create_response.json(), create_response.json()
        short_id = create_response.json()["short_id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}",
            {
                "type": "filters",
                "filters": updated_filters,
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_does_not_count_empty_object_as_filters(self) -> None:
        """
        can delete a collection despite there is an empty object for filters
        a regression test for https://github.com/PostHog/posthog/issues/35820
        """
        create_response = self._create_playlist({"type": "collection"})
        assert "short_id" in create_response.json(), create_response.json()
        short_id = create_response.json()["short_id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}",
            {"filters": {}, "deleted": True},
        )
        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_cannot_update_collection_to_have_filters(self) -> None:
        create_response = self._create_playlist({"type": "collection"})
        assert "short_id" in create_response.json(), create_response.json()
        short_id = create_response.json()["short_id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}",
            {"filters": {"events": [{"id": "test"}]}},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_rejects_updates_to_readonly_playlist_properties(self):
        # Create a playlist with a specific initial type
        initial_type = SessionRecordingPlaylist.PlaylistType.COLLECTION
        create_response = self._create_playlist({"name": "initial for readonly test", "type": initial_type})
        created_data = create_response.json()
        short_id = created_data["short_id"]
        assert created_data["type"] == initial_type  # Verify initial type

        new_type_attempt = SessionRecordingPlaylist.PlaylistType.FILTERS
        # Ensure we're trying to change to a different, valid type
        assert new_type_attempt != initial_type and new_type_attempt in SessionRecordingPlaylist.PlaylistType.values

        response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recording_playlists/{short_id}",
            {
                "short_id": "something else",  # Attempt to change a known read-only field
                "type": new_type_attempt,  # Attempt to change the now read-only 'type' field
                "name": "updated name for readonly test",  # A mutable field
                "pinned": True,  # Another mutable field
            },
            format="json",  # Explicitly set format for clarity
        )

        assert response.status_code == status.HTTP_200_OK  # Request should succeed
        updated_data = response.json()

        assert updated_data["short_id"] == short_id  # short_id should not have changed
        assert updated_data["type"] == initial_type  # type should not have changed
        assert updated_data["name"] == "updated name for readonly test"  # name should have been updated
        assert updated_data["pinned"] is True  # pinned should have been updated

    @parameterized.expand(
        [
            ["search_my", "search=my", [2]],
            ["search_playlist", "search=playlist", [2, 0]],
            ["user_true", "user=true", [1, 0]],
            ["pinned_true", "pinned=true", [1]],
            ["created_by_other", "created_by={other_user_id}", [2]],
        ]
    )
    def test_filters_based_on_params(
        self, _name: str, query_template: str, expected_playlist_indices: list[int]
    ) -> None:
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        playlists = [
            SessionRecordingPlaylist.objects.create(team=self.team, name="playlist", created_by=self.user),
            SessionRecordingPlaylist.objects.create(team=self.team, pinned=True, created_by=self.user),
            SessionRecordingPlaylist.objects.create(team=self.team, name="my playlist", created_by=other_user),
        ]

        query_params = f"?{query_template.format(other_user_id=other_user.id)}"
        results = self._get_non_synthetic_playlists(query_params, expected_synthetic_count=0)

        assert len(results) == len(expected_playlist_indices)
        for i, playlist_idx in enumerate(expected_playlist_indices):
            assert results[i]["short_id"] == playlists[playlist_idx].short_id

    def test_filters_saved_filters_type(self):
        # Create a playlist with pinned recordings and no filters
        playlist1 = SessionRecordingPlaylist.objects.create(
            team=self.team, name="pinned only", created_by=self.user, type="collection"
        )
        recording1 = SessionRecording.objects.create(team=self.team, session_id=str(uuid4()))
        SessionRecordingPlaylistItem.objects.create(playlist=playlist1, recording=recording1)

        # Create a playlist with both pinned recordings and filters
        playlist2 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="pinned and filters",
            created_by=self.user,
            filters={"events": [{"id": "test"}]},
            type="collection",
        )
        recording2 = SessionRecording.objects.create(team=self.team, session_id=str(uuid4()))
        SessionRecordingPlaylistItem.objects.create(playlist=playlist2, recording=recording2)

        # Create a playlist with only filters
        playlist3 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="filters only",
            created_by=self.user,
            filters={"events": [{"id": "test"}]},
            type="filters",
        )

        # Create a playlist with only deleted pinned items
        playlist4 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="deleted pinned only",
            created_by=self.user,
            type="collection",
        )
        recording4 = SessionRecording.objects.create(team=self.team, session_id=str(uuid4()))
        SessionRecordingPlaylistItem.objects.create(playlist=playlist4, recording=recording4)
        SessionRecordingPlaylistItem.objects.filter(playlist=playlist4, recording=recording4).update(deleted=True)

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists?type=filters",
        )
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]

        # Should only return the playlist with filters and no pinned recordings
        # since playlist 4 only has deleted pinned items, then it technically has no pinned
        # so counts has having 0 pinned items
        # but it also has no filters, so it should not be included
        assert [r["name"] for r in results] == [playlist3.name]

    def test_cannot_pin_items_to_filters_type_playlist(self):
        """
        Playlists with type=filters are dynamic and based only on the filter criteria.
        Pinning specific items is only allowed for type=collection playlists.
        """
        # Create a playlist explicitly marked as filters type
        response = self._create_playlist(
            {"name": "test filters only", "type": "filters", "filters": {"wat": "am filter"}}
        )
        playlist_id = response.json()["id"]
        playlist = SessionRecordingPlaylist.objects.get(id=playlist_id)
        assert playlist.type == SessionRecordingPlaylist.PlaylistType.FILTERS

        recording_session_id = "test_session_id"
        # Attempt to add (pin) a recording to this filters-type playlist
        add_item_response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/{recording_session_id}",
        )

        # Assert that the attempt fails with a 400 Bad Request
        assert add_item_response.status_code == status.HTTP_400_BAD_REQUEST
        assert add_item_response.json() == {
            "type": "validation_error",
            "code": "invalid_input",
            "detail": "Cannot add recordings to a playlist that is type 'filters'.",
            "attr": None,
        }

        # Verify no item was actually added
        assert SessionRecordingPlaylistItem.objects.filter(playlist=playlist).count() == 0

    @patch("posthog.session_recordings.session_recording_v2_service.copy_to_lts")
    def test_get_pinned_recordings_for_playlist(self, mock_copy_to_lts: MagicMock) -> None:
        mock_copy_to_lts.return_value = "some-lts-path"

        playlist = SessionRecordingPlaylist.objects.create(team=self.team, name="playlist", created_by=self.user)

        session_one = f"test_fetch_playlist_recordings-session1-{uuid4()}"
        session_two = f"test_fetch_playlist_recordings-session2-{uuid4()}"
        three_days_ago = (datetime.now() - timedelta(days=3)).replace(tzinfo=UTC)

        produce_replay_summary(
            team_id=self.team.id,
            session_id=session_one,
            distinct_id="123",
            first_timestamp=three_days_ago,
            last_timestamp=three_days_ago,
        )

        produce_replay_summary(
            team_id=self.team.id,
            session_id=session_two,
            distinct_id="123",
            first_timestamp=three_days_ago,
            last_timestamp=three_days_ago,
        )

        # Create playlist items
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/{session_one}"
        )
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/{session_two}"
        )
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/session-missing"
        )

        # Test get recordings
        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings"
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()

        assert len(result["results"]) == 2
        assert {x["id"] for x in result["results"]} == {session_one, session_two}

    @patch("posthog.session_recordings.session_recording_v2_service.copy_to_lts")
    def test_fetch_playlist_recordings(self, mock_copy_to_lts: MagicMock) -> None:
        # all sessions have been blob ingested and had data to copy into the LTS storage location
        mock_copy_to_lts.return_value = "some-lts-path"

        playlist1 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="playlist1",
            created_by=self.user,
        )
        playlist2 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="playlist2",
            created_by=self.user,
        )

        session_one = f"test_fetch_playlist_recordings-session1-{uuid4()}"
        session_two = f"test_fetch_playlist_recordings-session2-{uuid4()}"
        three_days_ago = (datetime.now() - timedelta(days=3)).replace(tzinfo=UTC)

        for session_id in [session_one, session_two]:
            produce_replay_summary(
                team_id=self.team.id,
                session_id=session_id,
                distinct_id="123",
                first_timestamp=three_days_ago,
                last_timestamp=three_days_ago,
            )

        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{session_one}",
        )
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{session_two}",
        )
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist2.short_id}/recordings/{session_one}",
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings",
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()

        assert len(result["results"]) == 2
        assert {x["id"] for x in result["results"]} == {session_one, session_two}

        # Test get recordings
        result = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist2.short_id}/recordings",
        ).json()

        assert len(result["results"]) == 1
        assert result["results"][0]["id"] == session_one

    def test_add_remove_static_playlist_items(self):
        playlist1 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="playlist1",
            created_by=self.user,
        )
        playlist2 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="playlist2",
            created_by=self.user,
        )

        recording1_session_id = "1"
        recording2_session_id = "2"

        # Add recording 1 to playlist 1
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{recording1_session_id}",
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()
        assert result["success"]
        playlist_item = SessionRecordingPlaylistItem.objects.filter(
            playlist_id=playlist1.id, session_id=recording1_session_id
        )
        assert playlist_item is not None

        # Add recording 2 to playlist 1
        result = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{recording2_session_id}",
        ).json()
        assert result["success"]
        playlist_item = SessionRecordingPlaylistItem.objects.filter(
            playlist_id=playlist1.id, session_id=recording2_session_id
        )
        assert playlist_item is not None

        # Add recording 2 to playlist 2
        result = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist2.short_id}/recordings/{recording2_session_id}",
        ).json()
        assert result["success"]
        playlist_item = SessionRecordingPlaylistItem.objects.filter(
            playlist_id=playlist2.id, session_id=recording2_session_id
        )
        assert playlist_item is not None

        session_recording_obj_1 = SessionRecording.get_or_build(team=self.team, session_id=recording1_session_id)
        assert session_recording_obj_1

        session_recording_obj_2 = SessionRecording.get_or_build(team=self.team, session_id=recording2_session_id)
        assert session_recording_obj_2

        # Delete playlist items
        result = self.client.delete(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{recording1_session_id}",
        ).json()
        assert result["success"]
        assert (
            SessionRecordingPlaylistItem.objects.filter(
                playlist_id=playlist1.id, session_id=recording1_session_id
            ).count()
            == 0
        )
        result = self.client.delete(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/{recording2_session_id}",
        ).json()
        assert result["success"]
        assert (
            SessionRecordingPlaylistItem.objects.filter(
                playlist_id=playlist1.id, session_id=recording2_session_id
            ).count()
            == 0
        )
        result = self.client.delete(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist2.short_id}/recordings/{recording2_session_id}",
        ).json()
        assert result["success"]
        assert (
            SessionRecordingPlaylistItem.objects.filter(
                playlist_id=playlist2.id, session_id=recording1_session_id
            ).count()
            == 0
        )

    @snapshot_postgres_queries
    @freeze_time("2025-01-01T12:00:00Z")
    def test_filters_playlist_by_type(self):
        # Setup playlists with different types and conditions
        p_filters_explicit = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="Filters Explicit",
            filters={"events": [{"id": "test"}]},
            type=SessionRecordingPlaylist.PlaylistType.FILTERS,
        )
        p_collection_explicit_items = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="Collection Explicit Items",
            filters={"events": [{"id": "test"}]},
            type=SessionRecordingPlaylist.PlaylistType.COLLECTION,
        )
        p_collection_explicit_no_filters = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="Collection Explicit No Filters",
            type=SessionRecordingPlaylist.PlaylistType.COLLECTION,
        )

        # Add items to relevant playlists
        recording = SessionRecording.objects.create(team=self.team, session_id=str(uuid4()))
        SessionRecordingPlaylistItem.objects.create(playlist=p_collection_explicit_items, recording=recording)
        SessionRecordingPlaylistItem.objects.create(playlist=p_collection_explicit_no_filters, recording=recording)

        # Test filtering by type=filters
        response_filters = self.client.get(f"/api/projects/{self.team.id}/session_recording_playlists?type=filters")
        assert response_filters.status_code == status.HTTP_200_OK
        results_filters = response_filters.json()["results"]
        assert len(results_filters) == 1
        assert {p["id"] for p in results_filters} == {p_filters_explicit.id}

        # Test filtering by type=collection
        results_collection = self._get_non_synthetic_playlists("?type=collection")
        assert {p["id"] for p in results_collection} == {
            p_collection_explicit_items.id,
            p_collection_explicit_no_filters.id,
        }

        # Test listing without type filter (should include all non-deleted)
        # TODO should we allow interacting without specifying type?
        results_all = self._get_non_synthetic_playlists()
        # Assuming no other playlists were created in the setup
        assert len(results_all) == 3

    @parameterized.expand(
        [
            ["no_filter", "", 6, 2],
            ["custom_only", "?collection_type=custom", 0, 2],
            ["synthetic_only", "?collection_type=synthetic", 6, 0],
        ]
    )
    def test_filters_playlist_by_collection_type(
        self,
        _name: str,
        query_params: str,
        expected_synthetic_count: int,
        expected_custom_count: int,
    ) -> None:
        p_collection_one = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="Custom Collection One",
            type=SessionRecordingPlaylist.PlaylistType.COLLECTION,
        )
        p_collection_two = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="Custom Collection Two",
            type=SessionRecordingPlaylist.PlaylistType.COLLECTION,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/session_recording_playlists{query_params}")
        assert response.status_code == status.HTTP_200_OK

        results = response.json()["results"]
        synthetic_results = [p for p in results if p.get("is_synthetic")]
        custom_results = [p for p in results if not p.get("is_synthetic")]

        assert len(synthetic_results) == expected_synthetic_count
        assert len(custom_results) == expected_custom_count

        if expected_custom_count > 0:
            assert {p["id"] for p in custom_results} == {p_collection_one.id, p_collection_two.id}

    def test_create_playlist_in_specific_folder(self):
        response = self._create_playlist(
            {
                "name": "Playlist in folder",
                "filters": {"events": [{"id": "$pageview"}]},
                "type": "filters",
                "_create_in_folder": "Special Folder/Session Recordings",
            }
        )
        playlist_id = response.json()["short_id"]

        assert playlist_id is not None

        fs_entry = FileSystem.objects.filter(
            team=self.team, ref=str(playlist_id), type="session_recording_playlist"
        ).first()
        assert fs_entry is not None
        assert "Special Folder/Session Recordings" in fs_entry.path

    @parameterized.expand(
        [
            ["single_recording", 1],
            ["small_batch", 3],
            ["large_batch", 15],
        ]
    )
    def test_bulk_add_remove_playlist_items(self, _name: str, count: int) -> None:
        playlist1 = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="bulk playlist",
            created_by=self.user,
            type=SessionRecordingPlaylist.PlaylistType.COLLECTION,
        )

        recording_ids = [f"bulk_session_{i}" for i in range(count)]

        # Test bulk add
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/bulk_add",
            {"session_recording_ids": recording_ids},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()
        assert result["success"] is True
        assert result["added_count"] == count
        assert result["total_requested"] == count

        # Verify items were created
        for recording_id in recording_ids:
            assert SessionRecordingPlaylistItem.objects.filter(
                playlist=playlist1, recording__session_id=recording_id
            ).exists()

        # Test bulk delete
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist1.short_id}/recordings/bulk_delete",
            {"session_recording_ids": recording_ids},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()
        assert result["success"] is True
        assert result["deleted_count"] == count
        assert result["total_requested"] == count

        # Verify items were deleted
        for recording_id in recording_ids:
            assert not SessionRecordingPlaylistItem.objects.filter(
                playlist=playlist1, recording__session_id=recording_id
            ).exists()

    @parameterized.expand(
        [
            ["empty_array", [], "must be provided as a non-empty array"],
            ["non_array_input", "not_an_array", None],
            [
                "too_many_recordings",
                [f"session_{i}" for i in range(21)],
                "Cannot process more than 20 recordings at once",
            ],
        ]
    )
    def test_bulk_add_validation_errors(
        self, _name: str, session_recording_ids: list | str, expected_error_substring: str | None
    ) -> None:
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="bulk validation playlist",
            created_by=self.user,
            type=SessionRecordingPlaylist.PlaylistType.COLLECTION,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/bulk_add",
            {"session_recording_ids": session_recording_ids},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        if expected_error_substring:
            assert expected_error_substring in response.json()["detail"]

    def test_cannot_bulk_add_to_filters_playlist(self):
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="filters only playlist",
            created_by=self.user,
            type=SessionRecordingPlaylist.PlaylistType.FILTERS,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/bulk_add",
            {"session_recording_ids": ["session_1", "session_2"]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Cannot add recordings to a playlist that is type 'filters'" in response.json()["detail"]

    def test_bulk_add_partial_success(self):
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="partial success playlist",
            created_by=self.user,
            type=SessionRecordingPlaylist.PlaylistType.COLLECTION,
        )

        # Add one recording first
        existing_id = "existing_session"
        self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/{existing_id}"
        )

        # Try to bulk add including the existing one and new ones
        recording_ids = [existing_id, "new_session_1", "new_session_2"]
        response = self.client.post(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/bulk_add",
            {"session_recording_ids": recording_ids},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        result = response.json()
        assert result["success"] is True
        assert result["added_count"] == 2  # Only new ones counted
        assert result["total_requested"] == 3
