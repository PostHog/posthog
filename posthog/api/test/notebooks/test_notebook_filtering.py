from typing import Dict, Any, List

from rest_framework import status

from posthog.test.base import APIBaseTest, QueryMatchingTest

PLAYLIST_CONTENT = lambda: {
    "type": "ph-recording-playlist",
    "attrs": {
        "filters": '{"specific_filters": "in here"}',
    },
}

FEATURE_FLAG_CONTENT = lambda id: {
    "type": "ph-feature-flag",
    "attrs": {
        "id": id or "feature_flag_id",
    },
}

PERSON_CONTENT = lambda id: {"type": "ph-person", "attrs": {"id": id or "person_id"}}

RECORDING_CONTENT = lambda id: {"type": "ph-recording", "attrs": {"id": id or "session_recording_id"}}
RECORDING_COMMENT_CONTENT = lambda id: {
    "type": "ph-replay-timestamp",
    "attrs": {"playbackTime": 52000, "sessionRecordingId": id or "session_recording_id"},
}

INSIGHT_COMMENT = lambda id: {
    "type": "ph-insight",
    "attrs": {
        "id": id or "insight_short_id",
    },
}


class TestNotebooksFiltering(APIBaseTest, QueryMatchingTest):
    def _create_notebook_with_content(self, inner_content: List[Dict[str, Any]]) -> str:
        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks",
            data={
                "content": {
                    "type": "doc",
                    "content": inner_content,
                }
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        return response.json()["id"]

    def test_filtering_by_types(self) -> None:
        playlist_content_notebook = self._create_notebook_with_content([PLAYLIST_CONTENT()])
        insight_content_notebook = self._create_notebook_with_content([INSIGHT_COMMENT("insight_id")])
        feature_flag_content_notebook = self._create_notebook_with_content([FEATURE_FLAG_CONTENT("feature_flag_id")])
        person_content_notebook = self._create_notebook_with_content([PERSON_CONTENT("person_id")])
        recording_comment_notebook = self._create_notebook_with_content(
            [RECORDING_COMMENT_CONTENT("session_recording_id")]
        )
        recording_content_notebook = self._create_notebook_with_content([RECORDING_CONTENT("recording_one")])

        # no filter
        no_filter_response = self.client.get(f"/api/projects/{self.team.id}/notebooks")
        assert len(no_filter_response.json()["results"]) == 6

        # filter by insight
        insight_filter_response = self.client.get(f"/api/projects/{self.team.id}/notebooks?contains=insight:true")
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
        insight_content_notebook = self._create_notebook_with_content([INSIGHT_COMMENT("insight_id")])
        feature_flag_content_notebook = self._create_notebook_with_content([FEATURE_FLAG_CONTENT("feature_flag_id")])
        person_content_notebook = self._create_notebook_with_content([PERSON_CONTENT("person_id")])
        recording_comment_notebook = self._create_notebook_with_content(
            [RECORDING_COMMENT_CONTENT("session_recording_id")]
        )
        recording_content_notebook = self._create_notebook_with_content([RECORDING_CONTENT("recording_one")])

        # no filter
        no_filter_response = self.client.get(f"/api/projects/{self.team.id}/notebooks")
        assert len(no_filter_response.json()["results"]) == 6

        # filter by insight
        insight_filter_response = self.client.get(f"/api/projects/{self.team.id}/notebooks?contains=insight:false")
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

    def test_filtering_by_id_of_types(self) -> None:
        self._create_notebook_with_content([PLAYLIST_CONTENT()])

        insight_content_notebook_one = self._create_notebook_with_content([INSIGHT_COMMENT("insight_id_one")])
        _insight_content_notebook_two = self._create_notebook_with_content([INSIGHT_COMMENT("insight_id_two")])

        feature_flag_content_notebook_one = self._create_notebook_with_content(
            [FEATURE_FLAG_CONTENT("feature_flag_id_one")]
        )
        _feature_flag_content_notebook_two = self._create_notebook_with_content(
            [FEATURE_FLAG_CONTENT("feature_flag_id_two")]
        )

        person_content_notebook_one = self._create_notebook_with_content([PERSON_CONTENT("person_id_one")])
        _person_content_notebook_two = self._create_notebook_with_content([PERSON_CONTENT("person_id_two")])

        recording_comment_notebook_one = self._create_notebook_with_content(
            [RECORDING_COMMENT_CONTENT("session_recording_id_one")]
        )
        _recording_comment_notebook_two = self._create_notebook_with_content(
            [RECORDING_COMMENT_CONTENT("session_recording_id_two")]
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
            f"/api/projects/{self.team.id}/notebooks?contains=insight:insight_id_one"
        )
        assert sorted([n["id"] for n in insight_filter_response.json()["results"]]) == sorted(
            [
                insight_content_notebook_one,
            ]
        )

        # filter by feature flag
        feature_flag_filter_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?contains=feature-flag:feature_flag_id_one"
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
        recording_one_node = {"type": "ph-recording", "attrs": {"id": "recording_one", "height": None}}
        recording_two_node = {"type": "ph-recording", "attrs": {"id": "recording_two", "height": None}}

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
