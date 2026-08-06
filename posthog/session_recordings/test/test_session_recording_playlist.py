import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, QueryMatchingTest, snapshot_postgres_queries
from unittest import mock
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from boto3 import resource
from botocore.config import Config
from parameterized import parameterized
from rest_framework import status

from posthog import redis
from posthog.models import Organization, PersonalAPIKey, SessionRecording, SessionRecordingPlaylistItem, Team
from posthog.models.file_system.file_system import FileSystem
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed
from posthog.session_recordings.models.session_recording_playlist import (
    SessionRecordingPlaylist,
    SessionRecordingPlaylistViewed,
)
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.session_recording_playlist_api import (
    MAX_SAVED_FILTER_SESSION_IDS_PER_PLAYLIST,
    PLAYLIST_COUNT_REDIS_PREFIX,
    PLAYLIST_LIST_MAX_LIMIT,
    _attach_empty_recordings_counts,
    _empty_saved_filters_counts,
    parse_non_negative_int,
    parse_positive_int,
    precompute_recordings_counts,
)
from posthog.session_recordings.synthetic_playlists import ExpiringPlaylistSource
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)

TEST_BUCKET = "test_storage_bucket-ee.TestSessionRecordingPlaylist"


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

    def _get_non_synthetic_playlists(self, query_params: str = "", expected_synthetic_count: int = 7) -> list[dict]:
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
        assert response_data["count"] == 9
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

    def test_list_does_not_issue_redundant_db_count(self) -> None:
        self._create_playlist({"name": "test", "type": "collection"})

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(f"/api/projects/{self.team.id}/session_recording_playlists")

        assert response.status_code == status.HTTP_200_OK

        playlist_count_queries = [
            q
            for q in ctx.captured_queries
            if "count(" in q["sql"].lower()
            and "posthog_sessionrecordingplaylist" in q["sql"].lower()
            and "posthog_sessionrecordingplaylistitem" not in q["sql"].lower()
        ]
        assert len(playlist_count_queries) == 1, (
            f"expected a single COUNT on the playlists table, saw {len(playlist_count_queries)}: "
            f"{[q['sql'] for q in playlist_count_queries]}"
        )

    @parameterized.expand(
        [
            [
                "without_type",
                {"name": "test"},
                {
                    "attr": None,
                    "code": "invalid_input",
                    "detail": "Must provide a valid playlist type: either filters or collection",
                    "type": "validation_error",
                },
            ],
            [
                "with_unknown_type",
                {"name": "test", "type": "tomato"},
                {
                    "attr": "type",
                    "code": "invalid_choice",
                    "detail": '"tomato" is not a valid choice.',
                    "type": "validation_error",
                },
            ],
        ]
    )
    def test_rejects_invalid_playlist_type(self, _name: str, playlist_data: dict, expected_response: dict) -> None:
        self._create_playlist(
            playlist_data,
            status.HTTP_400_BAD_REQUEST,
            expected_response_json=expected_response,
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
        # one query to get started and then 13 per creation (was 14, -1 after dropping duplicate session lookup)
        with self.assertNumQueries(13 * 50 + 1):
            for i in range(50):
                self._create_playlist({"name": f"test-{i}", "type": "collection"})

        # 13 per creation (was 14, -1 after dropping duplicate session lookup)
        with self.assertNumQueries(13 * 100):
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
            {
                "name": "test filters only",
                "type": "filters",
                "filters": {"wat": "am filter"},
            }
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

    def test_get_pinned_recordings_for_playlist(self) -> None:
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

    def test_fetch_playlist_recordings(self) -> None:
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

    def test_collection_recordings_keep_one_year_search_bound(self) -> None:
        # long retention keeps the old recording alive, so only the collections -1y bound excludes it
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team, name="collection", created_by=self.user, type="collection"
        )

        recent_session = f"recent-{uuid4()}"
        over_a_year_old_session = f"over-a-year-old-{uuid4()}"
        three_days_ago = (datetime.now() - timedelta(days=3)).replace(tzinfo=UTC)
        over_a_year_ago = (datetime.now() - timedelta(days=400)).replace(tzinfo=UTC)

        for session_id, timestamp in [(recent_session, three_days_ago), (over_a_year_old_session, over_a_year_ago)]:
            produce_replay_summary(
                team_id=self.team.id,
                session_id=session_id,
                distinct_id="123",
                first_timestamp=timestamp,
                last_timestamp=timestamp,
                retention_period_days=1826,
            )
            self.client.post(
                f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings/{session_id}"
            )

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings"
        )
        assert response.status_code == status.HTTP_200_OK
        assert {x["id"] for x in response.json()["results"]} == {recent_session}

    @parameterized.expand(
        [
            ("narrow_window_excludes", "-1d", False),
            ("covering_window_includes", "-30d", True),
        ]
    )
    def test_filters_playlist_pinned_recordings_respect_date_params(
        self, _name: str, date_from: str, expect_found: bool
    ) -> None:
        # legacy filters playlists can still carry pinned items
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team, name="legacy filters with pins", created_by=self.user, type="filters"
        )

        old_session = f"old-{uuid4()}"
        ten_days_ago = (datetime.now() - timedelta(days=10)).replace(tzinfo=UTC)
        produce_replay_summary(
            team_id=self.team.id,
            session_id=old_session,
            distinct_id="123",
            first_timestamp=ten_days_ago,
            last_timestamp=ten_days_ago,
        )
        # pinning via the API is collection-only, so create the legacy rows directly
        recording, _ = SessionRecording.objects.get_or_create(
            session_id=old_session, team=self.team, defaults={"deleted": False}
        )
        SessionRecordingPlaylistItem.objects.create(playlist=playlist, recording=recording)

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist.short_id}/recordings",
            data={"date_from": date_from},
        )
        assert response.status_code == status.HTTP_200_OK
        assert {x["id"] for x in response.json()["results"]} == ({old_session} if expect_found else set())

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

    @patch(
        "posthog.hogql.database.database.feature_enabled_or_false",
        new=MagicMock(return_value=False),
    )
    @snapshot_postgres_queries
    @freeze_time("2025-01-01T12:00:00Z")
    def test_filters_playlist_by_type(self):
        # Prime the expiring-playlist cache so its cold-start scan (which builds the
        # warehouse HogQL Database and emits a DataWarehouseSavedQuery lookup) stays
        # out of this query snapshot. The scan runs once per hour in production; left
        # to LocMemCache state it fires or not depending on test order, making the
        # captured query set flaky.
        cache.set(ExpiringPlaylistSource._get_cache_key(self.team.pk), [], ExpiringPlaylistSource.CACHE_TTL)

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
            ["no_filter", "", 7, 2],
            ["custom_only", "?collection_type=custom", 0, 2],
            ["synthetic_only", "?collection_type=synthetic", 7, 0],
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
            assert {p["id"] for p in custom_results} == {
                p_collection_one.id,
                p_collection_two.id,
            }

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
        self,
        _name: str,
        session_recording_ids: list | str,
        expected_error_substring: str | None,
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

    @parameterized.expand(
        [
            # (order, limit) across the synth/DB boundary, both sort directions.
            ["desc_boundary", "-last_modified_at", 30],
            ["desc_smaller", "-last_modified_at", 17],
            ["asc_boundary", "last_modified_at", 30],
            ["name_asc", "name", 12],
        ]
    )
    def test_pagination_covers_every_db_playlist_across_pages(self, _name: str, order: str, limit: int) -> None:
        # Walking every page must return each DB playlist exactly once with no empty
        # interior pages — synthetics displaced items off page boundaries before the fix.
        db_playlist_count = 50
        for i in range(db_playlist_count):
            SessionRecordingPlaylist.objects.create(
                team=self.team, name=f"playlist-{i:02d}", created_by=self.user, type="collection"
            )

        seen_db_ids: list[str] = []
        seen_synth_ids: set[str] = set()
        offset = 0
        total_count: int | None = None
        while True:
            response = self.client.get(
                f"/api/projects/{self.team.id}/session_recording_playlists?order={order}&limit={limit}&offset={offset}"
            )
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            total_count = data["count"]
            results = data["results"]
            # Synthetics may span several pages, so accumulate unique ids across the walk.
            seen_synth_ids.update(r["short_id"] for r in results if r.get("is_synthetic"))

            assert results, f"page at offset={offset} was unexpectedly empty"
            if offset + limit < total_count:
                assert len(results) == limit, "interior pages must be full"

            seen_db_ids.extend(r["short_id"] for r in results if not r.get("is_synthetic"))
            offset += limit
            if offset >= total_count:
                break

        assert len(seen_synth_ids) > 0, "test relies on synthetic playlists being present"
        assert total_count == db_playlist_count + len(seen_synth_ids)
        # Every DB playlist appears exactly once — no skips, no duplicates.
        assert len(seen_db_ids) == db_playlist_count
        assert len(set(seen_db_ids)) == db_playlist_count

    def test_pagination_returns_displaced_db_playlists_on_later_pages(self) -> None:
        # The reported bug: synthetics fill slots on page 1, so page 2 came back empty
        # while count still claimed more. Page 2 must return the displaced DB rows.
        page_size = 30
        db_playlist_count = page_size
        for i in range(db_playlist_count):
            SessionRecordingPlaylist.objects.create(
                team=self.team, name=f"playlist-{i:02d}", created_by=self.user, type="collection"
            )

        page_one = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists?limit={page_size}&offset=0"
        )
        assert page_one.status_code == status.HTTP_200_OK
        page_one_data = page_one.json()
        synth_count = sum(1 for r in page_one_data["results"] if r.get("is_synthetic"))
        total_count = page_one_data["count"]
        assert synth_count > 0, "test relies on synthetic playlists being present"
        assert total_count == db_playlist_count + synth_count
        assert len(page_one_data["results"]) == page_size
        assert page_one_data["next"] is not None
        assert page_one_data["previous"] is None

        page_two = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists?limit={page_size}&offset={page_size}"
        )
        assert page_two.status_code == status.HTTP_200_OK
        page_two_data = page_two.json()
        assert page_two_data["count"] == total_count
        # Displaced DB rows must appear here — previously this page was empty.
        assert len(page_two_data["results"]) == total_count - page_size
        assert all(not r.get("is_synthetic") for r in page_two_data["results"])
        assert page_two_data["previous"] is not None
        assert page_two_data["next"] is None

        # No overlap, and together they cover every DB playlist.
        page_one_db_ids = {r["short_id"] for r in page_one_data["results"] if not r.get("is_synthetic")}
        page_two_db_ids = {r["short_id"] for r in page_two_data["results"]}
        assert page_one_db_ids.isdisjoint(page_two_db_ids)
        assert len(page_one_db_ids | page_two_db_ids) == db_playlist_count

    def test_pagination_with_name_sort_places_synthetics_by_name(self) -> None:
        # Under name-ascending, synthetics sit at their alphabetical position, not
        # unconditionally at the start or end of the merged list.
        SessionRecordingPlaylist.objects.create(
            team=self.team, name="aaa-first", created_by=self.user, type="collection"
        )
        SessionRecordingPlaylist.objects.create(
            team=self.team, name="zzz-last", created_by=self.user, type="collection"
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists?order=name&limit=3&offset=0"
        )
        assert response.status_code == status.HTTP_200_OK
        names = [r["name"] for r in response.json()["results"]]
        # "aaa-first" sorts ahead of every synthetic, so page 1 must include it.
        assert "aaa-first" in names
        # "zzz-last" sorts after every synthetic; it must not appear on page 1.
        assert "zzz-last" not in names

    def test_pagination_with_name_sort_is_case_insensitive(self) -> None:
        # Rank math and the DB slice must share one case-insensitive order, else mixed-case
        # names get skipped or duplicated across pages.
        db_names = ["Banana", "apple", "Cherry", "date", "Elder", "fig", "Grape", "kiwi"]
        for name in db_names:
            SessionRecordingPlaylist.objects.create(team=self.team, name=name, created_by=self.user, type="collection")

        page_size = 5
        seen_db_names: list[str] = []
        offset = 0
        while True:
            response = self.client.get(
                f"/api/projects/{self.team.id}/session_recording_playlists?order=name&limit={page_size}&offset={offset}"
            )
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            seen_db_names.extend(r["name"] for r in data["results"] if not r.get("is_synthetic"))
            offset += page_size
            if offset >= data["count"]:
                break

        # Every DB playlist appears exactly once across all pages — no skips, no duplicates.
        assert sorted(seen_db_names) == sorted(db_names)

    def test_pagination_with_name_ties_across_page_boundary(self) -> None:
        # Duplicate names (including one colliding with a synthetic, "Expiring soon")
        # force ties that straddle page boundaries. The unique id tiebreaker must keep
        # every DB row appearing exactly once — without it the slice skips/repeats rows.
        created_ids: set[str] = set()
        for name in ["dup-a", "dup-a", "dup-a", "Expiring soon", "Expiring soon", "dup-z", "dup-z", "dup-z"]:
            playlist = SessionRecordingPlaylist.objects.create(
                team=self.team, name=name, created_by=self.user, type="collection"
            )
            created_ids.add(playlist.short_id)

        page_size = 3
        seen: list[str] = []
        offset = 0
        while True:
            response = self.client.get(
                f"/api/projects/{self.team.id}/session_recording_playlists?order=name&limit={page_size}&offset={offset}"
            )
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            seen.extend(r["short_id"] for r in data["results"] if not r.get("is_synthetic"))
            offset += page_size
            if offset >= data["count"]:
                break

        assert sorted(seen) == sorted(created_ids)
        assert len(seen) == len(set(seen))

    def test_pagination_synthetics_only_when_no_db_collections(self) -> None:
        # No DB rows: the response is exactly the synthetics, and paging across a small
        # limit returns each once — pins the rank range() branch with zero DB rows.
        page_size = 3
        seen: list[str] = []
        offset = 0
        total = 0
        while True:
            response = self.client.get(
                f"/api/projects/{self.team.id}/session_recording_playlists?limit={page_size}&offset={offset}"
            )
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            total = data["count"]
            assert all(r.get("is_synthetic") for r in data["results"])
            seen.extend(r["short_id"] for r in data["results"])
            offset += page_size
            if offset >= total:
                break

        assert total > 0
        assert len(seen) == total
        assert len(set(seen)) == total

    def test_pagination_with_zero_synthetics(self) -> None:
        # collection_type=custom filters out all synthetics, exercising the empty-ranks
        # early return; pure-DB pagination must still return each row exactly once.
        db_names = [f"custom-{i:02d}" for i in range(8)]
        for name in db_names:
            SessionRecordingPlaylist.objects.create(team=self.team, name=name, created_by=self.user, type="collection")

        page_size = 3
        seen: list[str] = []
        offset = 0
        total = 0
        while True:
            response = self.client.get(
                f"/api/projects/{self.team.id}/session_recording_playlists?collection_type=custom&limit={page_size}&offset={offset}"
            )
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            total = data["count"]
            assert not any(r.get("is_synthetic") for r in data["results"])
            seen.extend(r["name"] for r in data["results"])
            offset += page_size
            if offset >= total:
                break

        assert total == len(db_names)
        assert sorted(seen) == sorted(db_names)


class TestSessionRecordingPlaylistPersonalAPIKey(APIBaseTest):
    def _create_personal_api_key(self, scopes: list[str], scoped_teams: list[int] | None = None) -> str:
        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            last_used_at="2021-08-25T21:09:14",
            secure_value=hash_key_value(personal_api_key),
            scopes=scopes,
            scoped_teams=scoped_teams or [self.team.pk],
        )
        return personal_api_key

    @parameterized.expand(
        [
            ("list", "", status.HTTP_200_OK),
            ("retrieve", "/{short_id}", status.HTTP_200_OK),
            ("recordings", "/{short_id}/recordings", status.HTTP_200_OK),
        ]
    )
    def test_personal_api_key_can_access_read_endpoints(
        self, _name: str, path_suffix: str, expected_status: int
    ) -> None:
        playlist = SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test playlist",
            created_by=self.user,
            type=SessionRecordingPlaylist.PlaylistType.COLLECTION,
        )
        personal_api_key = self._create_personal_api_key(["session_recording_playlist:read"])
        url = (
            f"/api/projects/{self.team.pk}/session_recording_playlists{path_suffix.format(short_id=playlist.short_id)}"
        )

        response = self.client.get(url, headers={"authorization": f"Bearer {personal_api_key}"})

        assert response.status_code == expected_status

    @parameterized.expand(
        [
            ("wrong_scope", ["some_other_scope:read"], None),
            ("wrong_team", ["session_recording_playlist:read"], "other_team"),
        ]
    )
    def test_personal_api_key_denied_without_correct_scope_or_team(
        self, _name: str, scopes: list[str], scoped_team: str | None
    ) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other team")
        SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="test playlist",
            created_by=self.user,
            type=SessionRecordingPlaylist.PlaylistType.COLLECTION,
        )
        scoped_teams = [other_team.pk] if scoped_team == "other_team" else None
        personal_api_key = self._create_personal_api_key(scopes, scoped_teams)

        response = self.client.get(
            f"/api/projects/{self.team.pk}/session_recording_playlists",
            headers={"authorization": f"Bearer {personal_api_key}"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestSessionRecordingPlaylistTeamIsolation(APIBaseTest):
    def test_list_only_returns_own_team_playlists(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other team")
        SessionRecordingPlaylist.objects.create(
            team=other_team,
            name="other team playlist",
            created_by=self.user,
            type="collection",
        )
        SessionRecordingPlaylist.objects.create(
            team=self.team,
            name="my team playlist",
            created_by=self.user,
            type="collection",
        )

        response = self.client.get(f"/api/projects/{self.team.pk}/session_recording_playlists")

        assert response.status_code == status.HTTP_200_OK
        results = [r for r in response.json()["results"] if not r.get("is_synthetic")]
        assert len(results) == 1
        assert results[0]["name"] == "my team playlist"

    @parameterized.expand(
        [
            ("retrieve", "get", "/{short_id}", None),
            ("update", "patch", "/{short_id}", {"name": "hacked"}),
            ("recordings", "get", "/{short_id}/recordings", None),
            ("add_recording", "post", "/{short_id}/recordings/test_session", None),
        ]
    )
    def test_cannot_access_playlist_from_another_team(
        self, _name: str, method: str, path_suffix: str, data: dict | None
    ) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other team")
        playlist = SessionRecordingPlaylist.objects.create(
            team=other_team,
            name="other team playlist",
            created_by=self.user,
            type="collection",
        )
        url = (
            f"/api/projects/{self.team.pk}/session_recording_playlists{path_suffix.format(short_id=playlist.short_id)}"
        )

        response = getattr(self.client, method)(url, data) if data else getattr(self.client, method)(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cannot_access_playlists_from_different_organization(self) -> None:
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="other org team")

        response = self.client.get(f"/api/projects/{other_team.pk}/session_recording_playlists")

        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestPrecomputeRecordingsCounts(APIBaseTest):
    def _make_playlist(self, name: str, playlist_type: str = "collection") -> SessionRecordingPlaylist:
        return SessionRecordingPlaylist.objects.create(
            team=self.team,
            name=name,
            created_by=self.user,
            type=playlist_type,
        )

    @parameterized.expand(
        [
            ("all_synthetic", "synthetic"),
            ("empty_list", "empty"),
        ]
    )
    def test_noop_paths_do_not_attach_prefetch_attrs(self, _name: str, scenario: str) -> None:
        if scenario == "synthetic":
            playlist = SessionRecordingPlaylist(team=self.team, type="collection")
            playlist._is_synthetic = True  # type: ignore[attr-defined]
            playlists: list[SessionRecordingPlaylist] = [playlist]
        else:
            playlists = []

        precompute_recordings_counts(playlists, self.user, self.team)

        for playlist in playlists:
            assert not hasattr(playlist, "_prefetched_collection_count")
            assert not hasattr(playlist, "_prefetched_saved_filters_count")

    def test_collection_with_items_attaches_count(self) -> None:
        playlist = self._make_playlist("with items")
        for session_id in ["s1", "s2", "s3"]:
            recording = SessionRecording.objects.create(team=self.team, session_id=session_id)
            SessionRecordingPlaylistItem.objects.create(playlist=playlist, recording=recording)
        SessionRecordingViewed.objects.create(team=self.team, user=self.user, session_id="s1")
        SessionRecordingViewed.objects.create(team=self.team, user=self.user, session_id="s2")

        precompute_recordings_counts([playlist], self.user, self.team)

        assert playlist._prefetched_collection_count == {"count": 3, "watched_count": 2}  # type: ignore[attr-defined]
        assert not hasattr(playlist, "_prefetched_saved_filters_count")

    def test_collection_with_soft_deleted_items_excluded_from_count(self) -> None:
        playlist = self._make_playlist("all deleted")
        rec = SessionRecording.objects.create(team=self.team, session_id="deleted-1")
        SessionRecordingPlaylistItem.objects.create(playlist=playlist, recording=rec, deleted=True)
        SessionRecordingViewed.objects.create(team=self.team, user=self.user, session_id="deleted-1")

        precompute_recordings_counts([playlist], self.user, self.team)

        # count excludes the soft-deleted item (None), but watched_count includes it
        # to match the historical behavior of count_collection_recordings.
        assert playlist._prefetched_collection_count == {"count": None, "watched_count": 1}  # type: ignore[attr-defined]

    def test_empty_collection_loads_saved_filters_from_redis(self) -> None:
        playlist = self._make_playlist("empty")
        SessionRecordingViewed.objects.create(team=self.team, user=self.user, session_id="a")
        redis.get_client().set(
            f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}",
            json.dumps({"session_ids": ["a", "b"], "previous_ids": ["b"], "has_more": False}),
        )

        precompute_recordings_counts([playlist], self.user, self.team)

        assert playlist._prefetched_collection_count == {"count": None, "watched_count": 0}  # type: ignore[attr-defined]
        assert playlist._prefetched_saved_filters_count == {  # type: ignore[attr-defined]
            "count": 2,
            "has_more": False,
            "watched_count": 1,
            "increased": True,
            "last_refreshed_at": None,
        }

    def test_saved_filter_count_and_watched_stay_consistent_when_capped(self) -> None:
        # When a Redis payload contains more than MAX_SAVED_FILTER_SESSION_IDS_PER_PLAYLIST
        # session IDs, both `count` and `watched_count` must be derived from the same
        # capped list — otherwise watched_count can exceed count or reference IDs that
        # were never part of the MGET viewed-status lookup.
        playlist = self._make_playlist("huge saved filter")
        extra = 5
        total_ids = MAX_SAVED_FILTER_SESSION_IDS_PER_PLAYLIST + extra
        session_ids = [f"sid-{i}" for i in range(total_ids)]
        # Mark two sessions as viewed: one inside the cap and one outside.
        SessionRecordingViewed.objects.create(team=self.team, user=self.user, session_id="sid-0")
        SessionRecordingViewed.objects.create(
            team=self.team,
            user=self.user,
            session_id=f"sid-{MAX_SAVED_FILTER_SESSION_IDS_PER_PLAYLIST + 1}",
        )
        redis.get_client().set(
            f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}",
            json.dumps({"session_ids": session_ids, "previous_ids": [], "has_more": True}),
        )

        precompute_recordings_counts([playlist], self.user, self.team)

        result = playlist._prefetched_saved_filters_count  # type: ignore[attr-defined]
        assert result["count"] == MAX_SAVED_FILTER_SESSION_IDS_PER_PLAYLIST
        # Only the in-cap viewed session is counted.
        assert result["watched_count"] == 1

    def test_malformed_redis_payload_degrades_to_empty(self) -> None:
        playlist = self._make_playlist("bad redis")
        redis.get_client().set(f"{PLAYLIST_COUNT_REDIS_PREFIX}{playlist.short_id}", "not json")

        precompute_recordings_counts([playlist], self.user, self.team)

        assert playlist._prefetched_saved_filters_count == _empty_saved_filters_counts()  # type: ignore[attr-defined]

    def test_redis_mget_failure_degrades_without_raising(self) -> None:
        playlist = self._make_playlist("redis down")

        with patch("posthog.session_recordings.session_recording_playlist_api.get_client") as mock_get_client:
            mock_redis = MagicMock()
            mock_redis.mget.side_effect = RuntimeError("redis unavailable")
            mock_get_client.return_value = mock_redis

            precompute_recordings_counts([playlist], self.user, self.team)

        assert playlist._prefetched_collection_count == {"count": None, "watched_count": 0}  # type: ignore[attr-defined]
        assert playlist._prefetched_saved_filters_count == _empty_saved_filters_counts()  # type: ignore[attr-defined]

    def test_does_not_read_items_from_other_team(self) -> None:
        # Defense-in-depth: even if a caller misuses the helper by passing a
        # cross-team playlist id, items belonging to another team must not leak in.
        other_team = Team.objects.create(organization=self.organization, name="other")
        mine = self._make_playlist("mine")
        theirs = SessionRecordingPlaylist.objects.create(team=other_team, name="theirs", type="collection")
        rec = SessionRecording.objects.create(team=other_team, session_id="theirs-1")
        SessionRecordingPlaylistItem.objects.create(playlist=theirs, recording=rec)

        # Simulate a buggy caller passing both playlists.
        precompute_recordings_counts([mine, theirs], self.user, self.team)

        assert mine._prefetched_collection_count == {"count": None, "watched_count": 0}  # type: ignore[attr-defined]
        # The other-team playlist's items are filtered out by playlist__team_id.
        assert theirs._prefetched_collection_count == {"count": None, "watched_count": 0}  # type: ignore[attr-defined]

    @parameterized.expand(
        [
            ("sets_defaults", "default", {"count": None, "watched_count": None}, True),
            ("skips_synthetic", "synthetic", None, False),
            ("preserves_existing_attrs", "preexisting", {"count": 5, "watched_count": 1}, False),
        ]
    )
    def test_attach_empty_recordings_counts(
        self,
        _name: str,
        scenario: str,
        expected_collection_count: dict | None,
        expect_saved_filters_default: bool,
    ) -> None:
        if scenario == "synthetic":
            playlist = SessionRecordingPlaylist(team=self.team, type="collection")
            playlist._is_synthetic = True  # type: ignore[attr-defined]
        else:
            playlist = self._make_playlist(scenario)
            if scenario == "preexisting":
                playlist._prefetched_collection_count = {"count": 5, "watched_count": 1}  # type: ignore[attr-defined]

        _attach_empty_recordings_counts([playlist])

        if expected_collection_count is None:
            assert not hasattr(playlist, "_prefetched_collection_count")
        else:
            assert playlist._prefetched_collection_count == expected_collection_count  # type: ignore[attr-defined]

        if expect_saved_filters_default:
            assert playlist._prefetched_saved_filters_count == _empty_saved_filters_counts()  # type: ignore[attr-defined]

    def test_list_clamps_limit_query_param_to_max(self) -> None:
        # Sanity-check the pagination cap — requesting limit=99999 must cap at the configured max.
        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recording_playlists?limit={PLAYLIST_LIST_MAX_LIMIT + 100}"
        )
        assert response.status_code == status.HTTP_200_OK
        # Even with no playlists created, the response must be well-formed and bounded.
        # (Actual item count depends on synthetic playlists; the cap is enforced inside list()
        # and by the paginator.)
        results = response.json()["results"]
        assert len(results) <= PLAYLIST_LIST_MAX_LIMIT

    def test_list_with_zero_limit_does_not_loop_pagination(self) -> None:
        # limit=0 would make the next link point back at the same offset (infinite paging);
        # it must fall back to the default page size and terminate.
        response = self.client.get(f"/api/projects/{self.team.id}/session_recording_playlists?limit=0")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Default page size (100) comfortably holds the synthetics, so there's no next page
        # and certainly no self-referential loop.
        assert data["next"] is None
        assert len(data["results"]) == data["count"]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("30", 30),
        ("0", 0),
        ("-5", 0),
        ("abc", 100),
        (None, 100),
    ],
)
def test_parse_non_negative_int(value: object, expected: int) -> None:
    assert parse_non_negative_int(value, 100) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("30", 30),
        ("0", 100),  # limit=0 would loop pagination -> default
        ("-5", 100),  # non-positive -> default
        ("abc", 100),
        (None, 100),
    ],
)
def test_parse_positive_int(value: object, expected: int) -> None:
    assert parse_positive_int(value, 100) == expected
