from typing import Dict, Any

from rest_framework import status

from posthog.test.base import APIBaseTest, QueryMatchingTest


class TestNotebooksFiltering(APIBaseTest, QueryMatchingTest):
    def _create_notebook_with_content(self, content_with_a_recording: Dict[str, Any]) -> str:
        response = self.client.post(
            f"/api/projects/{self.team.id}/notebooks", data={"content": content_with_a_recording}
        )
        assert response.status_code == status.HTTP_201_CREATED
        return response.json()["id"]

    def test_notebook_with_any_recording(self) -> None:
        content_with_a_recording = {
            "type": "doc",
            "content": [
                {
                    "type": "ph-recording",
                }
            ],
        }

        content_without_recording = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                }
            ],
        }

        with_recording_id = self._create_notebook_with_content(content_with_a_recording)

        without_recording_id = self._create_notebook_with_content(content_without_recording)

        no_filter_response = self.client.get(f"/api/projects/{self.team.id}/notebooks")
        assert sorted([n["id"] for n in no_filter_response.json()["results"]]) == sorted(
            [
                with_recording_id,
                without_recording_id,
            ]
        )

        filter_present_response = self.client.get(f"/api/projects/{self.team.id}/notebooks?has_recording=true")
        assert [n["id"] for n in filter_present_response.json()["results"]] == [with_recording_id]

        filter_not_present_response = self.client.get(f"/api/projects/{self.team.id}/notebooks?has_recording=false")
        assert [n["id"] for n in filter_not_present_response.json()["results"]] == [without_recording_id]

    def test_notebook_with_specific_recording(self) -> None:
        recording_one_node = {"type": "ph-recording", "attrs": {"id": "recording_one", "height": None}}
        recording_two_node = {"type": "ph-recording", "attrs": {"id": "recording_two", "height": None}}
        content_with_both_recordings = {
            "type": "doc",
            "content": [recording_one_node, recording_two_node],
        }

        content_with_recording_one = {
            "type": "doc",
            "content": [recording_one_node],
        }

        content_with_recording_two = {
            "type": "doc",
            "content": [recording_two_node],
        }

        with_both_recording_id = self._create_notebook_with_content(content_with_both_recordings)
        with_recording_one_id = self._create_notebook_with_content(content_with_recording_one)
        with_recording_two_id = self._create_notebook_with_content(content_with_recording_two)

        no_filter_response = self.client.get(f"/api/projects/{self.team.id}/notebooks")
        assert sorted([n["id"] for n in no_filter_response.json()["results"]]) == sorted(
            [with_both_recording_id, with_recording_one_id, with_recording_two_id]
        )

        filter_recording_one_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?has_recording=recording_one"
        )
        assert [n["id"] for n in filter_recording_one_response.json()["results"]] == [
            with_recording_one_id,
            with_both_recording_id,
        ]

        filter_recording_two_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?has_recording=recording_two"
        )
        assert [n["id"] for n in filter_recording_two_response.json()["results"]] == [
            with_recording_two_id,
            with_both_recording_id,
        ]

        filter_unmatched_recordings_response = self.client.get(
            f"/api/projects/{self.team.id}/notebooks?has_recording=recording_three"
        )
        assert [n["id"] for n in filter_unmatched_recordings_response.json()["results"]] == []
