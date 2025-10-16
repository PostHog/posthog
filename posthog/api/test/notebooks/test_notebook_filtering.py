from typing import Any

from posthog.test.base import APIBaseTest, QueryMatchingTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import User

from products.notebooks.backend.models import Notebook

PLAYLIST_CONTENT = lambda: {
    "type": "ph-recording-playlist",
    "attrs": {
        "filters": '{"specific_filters": "in here"}',
    },
}

FEATURE_FLAG_CONTENT = lambda id: {
    "type": "ph-feature-flag",
    "attrs": {
        "id": id or 1,
    },
}

PERSON_CONTENT = lambda id: {"type": "ph-person", "attrs": {"id": id or "person_id"}}

RECORDING_CONTENT = lambda id: {
    "type": "ph-recording",
    "attrs": {"id": id or "session_recording_id"},
}
RECORDING_COMMENT_CONTENT = lambda id, text: {
    "type": "paragraph",
    "content": [
        {
            "type": "ph-replay-timestamp",
            "attrs": {
                "playbackTime": 0,
                "sessionRecordingId": id or "session_recording_id",
            },
        },
        {"text": text or "what the person typed", "type": "text"},
    ],
}

QUERY_CONTENT = lambda id: {
    "type": "ph-query",
    "attrs": {
        "query": {
            "kind": "SavedInsightNode",
            "shortId": id or "insight_short_id",
        }
    },
}

BASIC_TEXT = lambda text: {
    "type": "paragraph",
    "content": [{"text": text, "type": "text"}],
    "text_content": text,
}


class TestNotebooksFiltering(APIBaseTest, QueryMatchingTest):
    def _create_notebook_with_content(self, inner_content: list[dict[str, Any]], title: str = "the title") -> str:
        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks",
            data={
                "title": title,
                "content": {
                    "type": "doc",
                    "content": inner_content,
                },
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        return response.json()["id"]

    @parameterized.expand(
        [
            ["i ride", [0]],
            ["pony", [0]],
            ["ponies", [0]],
            ["my hobby", [1]],
            ["around", [0, 1]],
            ["random", []],
        ]
    )
    def test_filters_based_on_title(self, search_text: str, expected_match_indexes: list[int]) -> None:
        notebook_ids = [
            self._create_notebook_with_content([BASIC_TEXT("my important notes")], title="i ride around on a pony"),
            self._create_notebook_with_content([BASIC_TEXT("my important notes")], title="my hobby is to fish around"),
        ]

        response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?search={search_text}",
        )
        assert response.status_code == status.HTTP_200_OK

        results = response.json()["results"]
        assert len(results) == len(expected_match_indexes)
        assert sorted([r["id"] for r in results]) == sorted([notebook_ids[i] for i in expected_match_indexes])

        @parameterized.expand(
            [
                ["pony", [0]],
                ["pOnY", [0]],
                ["ponies", [0]],
                ["goat", [1]],
                ["ride", [0, 1]],
                ["neither", []],
            ]
        )
        def test_filters_based_on_text_content(self, search_text: str, expected_match_indexes: list[int]) -> None:
            notebook_ids = [
                # will match both pony and ponies
                self._create_notebook_with_content([BASIC_TEXT("you may ride a pony")], title="never matches"),
                self._create_notebook_with_content([BASIC_TEXT("but may not ride a goat")], title="never matches"),
            ]

            response = self.client.get(
                f"/api/projects/{self.team.id}/notebooks?search={search_text}",
            )
            assert response.status_code == status.HTTP_200_OK

            results = response.json()["results"]
            assert len(results) == len(expected_match_indexes)
            assert sorted([r["id"] for r in results]) == sorted([notebook_ids[i] for i in expected_match_indexes])

    def test_filters_based_on_params(self) -> None:
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password")
        notebook_one = Notebook.objects.create(team=self.team, created_by=self.user)
        notebook_two = Notebook.objects.create(team=self.team, created_by=self.user)
        other_users_notebook = Notebook.objects.create(team=self.team, created_by=other_user)

        results = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?user=true",
        ).json()["results"]

        assert [r["short_id"] for r in results] == [
            notebook_two.short_id,
            notebook_one.short_id,
        ]

        response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?created_by={other_user.uuid}",
        )
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]

        assert [r["short_id"] for r in results] == [other_users_notebook.short_id]

    def test_filtering_by_types(self) -> None:
        playlist_content_notebook = self._create_notebook_with_content([PLAYLIST_CONTENT()])
        insight_content_notebook = self._create_notebook_with_content([QUERY_CONTENT("insight_id")])
        feature_flag_content_notebook = self._create_notebook_with_content([FEATURE_FLAG_CONTENT(1)])
        person_content_notebook = self._create_notebook_with_content([PERSON_CONTENT("person_id")])
        recording_comment_notebook = self._create_notebook_with_content(
            [RECORDING_COMMENT_CONTENT("session_recording_id", None)]
        )
        recording_content_notebook = self._create_notebook_with_content([RECORDING_CONTENT("recording_one")])

        # no filter
        no_filter_response = self.client.get(f"/api/projects/{self.team.id}/notebooks")
        assert len(no_filter_response.json()["results"]) == 6

        # filter by insight
        insight_filter_response = self.client.get(f"/api/projects/{self.team.id}/notebooks?contains=query:true")
        assert [n["id"] for n in insight_filter_response.json()["results"]] == [insight_content_notebook]

        # filter by playlist
        playlist_filter_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?contains=recording-playlist:true"
        )
        assert [n["id"] for n in playlist_filter_response.json()["results"]] == [playlist_content_notebook]

        # filter by feature flag
        feature_flag_filter_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?contains=feature-flag:true"
        )
        assert [n["id"] for n in feature_flag_filter_response.json()["results"]] == [feature_flag_content_notebook]

        # filter by person
        person_filter_response = self.client.get(f"/api/projects/{self.team.id}/notebooks?contains=person:true")
        assert [n["id"] for n in person_filter_response.json()["results"]] == [person_content_notebook]

        # filter by recording comment
        recording_comment_filter_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?contains=replay-timestamp:true"
        )
        assert [n["id"] for n in recording_comment_filter_response.json()["results"]] == [recording_comment_notebook]

        # filter by recording
        recording_filter_response = self.client.get(f"/api/projects/{self.team.id}/notebooks?contains=recording:true")
        assert [n["id"] for n in recording_filter_response.json()["results"]] == [recording_content_notebook]

    def test_filtering_by_abscence_of_types(self) -> None:
        playlist_content_notebook = self._create_notebook_with_content([PLAYLIST_CONTENT()])
        insight_content_notebook = self._create_notebook_with_content([QUERY_CONTENT("insight_id")])
        feature_flag_content_notebook = self._create_notebook_with_content([FEATURE_FLAG_CONTENT(1)])
        person_content_notebook = self._create_notebook_with_content([PERSON_CONTENT("person_id")])
        recording_comment_notebook = self._create_notebook_with_content(
            [RECORDING_COMMENT_CONTENT("session_recording_id", None)]
        )
        recording_content_notebook = self._create_notebook_with_content([RECORDING_CONTENT("recording_one")])

        # no filter
        no_filter_response = self.client.get(f"/api/projects/{self.team.id}/notebooks")
        assert len(no_filter_response.json()["results"]) == 6

        # filter by insight
        insight_filter_response = self.client.get(f"/api/projects/{self.team.id}/notebooks?contains=query:false")
        assert sorted([n["id"] for n in insight_filter_response.json()["results"]]) == sorted(
            [
                playlist_content_notebook,
                feature_flag_content_notebook,
                person_content_notebook,
                recording_comment_notebook,
                recording_content_notebook,
            ]
        )

        # filter by playlist
        playlist_filter_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?contains=recording-playlist:false"
        )
        assert sorted([n["id"] for n in playlist_filter_response.json()["results"]]) == sorted(
            [
                feature_flag_content_notebook,
                person_content_notebook,
                recording_comment_notebook,
                recording_content_notebook,
                insight_content_notebook,
            ]
        )

        # filter by feature flag
        feature_flag_filter_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?contains=feature-flag:false"
        )
        assert sorted([n["id"] for n in feature_flag_filter_response.json()["results"]]) == sorted(
            [
                playlist_content_notebook,
                person_content_notebook,
                recording_comment_notebook,
                recording_content_notebook,
                insight_content_notebook,
            ]
        )

        # filter by person
        person_filter_response = self.client.get(f"/api/projects/{self.team.id}/notebooks?contains=person:false")
        assert sorted([n["id"] for n in person_filter_response.json()["results"]]) == sorted(
            [
                playlist_content_notebook,
                feature_flag_content_notebook,
                recording_comment_notebook,
                recording_content_notebook,
                insight_content_notebook,
            ]
        )

        # filter by recording comment
        recording_comment_filter_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?contains=replay-timestamp:false"
        )
        assert sorted([n["id"] for n in recording_comment_filter_response.json()["results"]]) == sorted(
            [
                playlist_content_notebook,
                feature_flag_content_notebook,
                person_content_notebook,
                recording_content_notebook,
                insight_content_notebook,
            ]
        )

        # filter by recording
        recording_filter_response = self.client.get(f"/api/projects/{self.team.id}/notebooks?contains=recording:false")
        assert sorted([n["id"] for n in recording_filter_response.json()["results"]]) == sorted(
            [
                playlist_content_notebook,
                feature_flag_content_notebook,
                person_content_notebook,
                recording_comment_notebook,
                insight_content_notebook,
            ]
        )

    @parameterized.expand([["query"], ["queries"]])
    def test_filtering_by_just_the_target_name_is_truthy(self, target_name: str) -> None:
        insight_content_notebook_one = self._create_notebook_with_content([QUERY_CONTENT("insight_id_one")])
        _feature_flag_content_notebook_one = self._create_notebook_with_content([FEATURE_FLAG_CONTENT(1)])
        filter_response = self.client.get(f"/api/projects/{self.team.id}/notebooks?contains={target_name}")
        assert sorted([n["id"] for n in filter_response.json()["results"]]) == sorted(
            [
                insight_content_notebook_one,
            ]
        )

    def test_filtering_by_id_of_types(self) -> None:
        self._create_notebook_with_content([PLAYLIST_CONTENT()])

        insight_content_notebook_one = self._create_notebook_with_content([QUERY_CONTENT("insight_id_one")])
        _insight_content_notebook_two = self._create_notebook_with_content([QUERY_CONTENT("insight_id_two")])

        feature_flag_content_notebook_one = self._create_notebook_with_content([FEATURE_FLAG_CONTENT(1)])
        _feature_flag_content_notebook_two = self._create_notebook_with_content([FEATURE_FLAG_CONTENT(2)])

        person_content_notebook_one = self._create_notebook_with_content([PERSON_CONTENT("person_id_one")])
        _person_content_notebook_two = self._create_notebook_with_content([PERSON_CONTENT("person_id_two")])

        recording_comment_notebook_one = self._create_notebook_with_content(
            [RECORDING_COMMENT_CONTENT("session_recording_id_one", None)]
        )
        _recording_comment_notebook_two = self._create_notebook_with_content(
            [RECORDING_COMMENT_CONTENT("session_recording_id_two", None)]
        )

        recording_content_notebook_one = self._create_notebook_with_content(
            [RECORDING_CONTENT("session_recording_id_one")]
        )
        _recording_content_notebook_two = self._create_notebook_with_content(
            [RECORDING_CONTENT("session_recording_id_two")]
        )

        # no filter
        no_filter_response = self.client.get(f"/api/projects/{self.team.id}/notebooks")
        assert len(no_filter_response.json()["results"]) == 11

        # filter by insight
        insight_filter_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?contains=query:insight_id_one"
        )
        assert sorted([n["id"] for n in insight_filter_response.json()["results"]]) == sorted(
            [
                insight_content_notebook_one,
            ]
        )

        # filter by feature flag
        feature_flag_filter_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?contains=feature-flag:1"
        )
        assert sorted([n["id"] for n in feature_flag_filter_response.json()["results"]]) == sorted(
            [
                feature_flag_content_notebook_one,
            ]
        )

        # filter by person
        person_filter_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?contains=person:person_id_one"
        )
        assert sorted([n["id"] for n in person_filter_response.json()["results"]]) == sorted(
            [
                person_content_notebook_one,
            ]
        )

        # filter by recording comment
        recording_comment_filter_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?contains=replay-timestamp:session_recording_id_one"
        )
        assert sorted([n["id"] for n in recording_comment_filter_response.json()["results"]]) == sorted(
            [
                recording_comment_notebook_one,
            ]
        )

        # filter by recording
        recording_filter_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?contains=recording:session_recording_id_one"
        )
        assert sorted([n["id"] for n in recording_filter_response.json()["results"]]) == sorted(
            [
                recording_content_notebook_one,
            ]
        )

    def test_notebook_filter_can_combine(self) -> None:
        recording_one_node = {
            "type": "ph-recording",
            "attrs": {"id": "recording_one", "height": None},
        }
        recording_two_node = {
            "type": "ph-recording",
            "attrs": {"id": "recording_two", "height": None},
        }

        content_with_both_recordings = [recording_one_node, recording_two_node]
        content_with_recording_one = [recording_one_node]
        content_with_recording_two = [recording_two_node]

        with_both_recording_id = self._create_notebook_with_content(content_with_both_recordings)
        with_recording_one_id = self._create_notebook_with_content(content_with_recording_one)
        with_recording_two_id = self._create_notebook_with_content(content_with_recording_two)

        no_filter_response = self.client.get(f"/api/projects/{self.team.id}/notebooks")
        assert sorted([n["id"] for n in no_filter_response.json()["results"]]) == sorted(
            [with_both_recording_id, with_recording_one_id, with_recording_two_id]
        )

        filter_recording_two_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?contains=recording:recording_two"
        )
        assert [n["id"] for n in filter_recording_two_response.json()["results"]] == [
            with_recording_two_id,
            with_both_recording_id,
        ]

        filter_unmatched_recordings_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?contains=recording:recording_three"
        )
        assert [n["id"] for n in filter_unmatched_recordings_response.json()["results"]] == []

        # with multiple match pairs
        filter_recording_should_not_match_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?contains=recording:false,recording:recording_two"
        )
        assert [n["id"] for n in filter_recording_should_not_match_response.json()["results"]] == []

        filter_recording_should_match_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?contains=recording:true recording:recording_two"
        )
        assert [n["id"] for n in filter_recording_should_match_response.json()["results"]] == [
            with_recording_two_id,
            with_both_recording_id,
        ]
