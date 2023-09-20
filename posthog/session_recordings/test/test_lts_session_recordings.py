import uuid
from typing import List
from unittest.mock import patch, MagicMock, call, Mock

from posthog.models import Team
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest


class TestSessionRecordings(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        # Create a new team each time to ensure no clashing between tests
        self.team = Team.objects.create(organization=self.organization, name="New Team")

    @patch("posthog.session_recordings.session_recording_api.object_storage.list_objects")
    def test_2023_08_01_version_stored_snapshots_can_be_gathered(self, mock_list_objects: MagicMock) -> None:
        session_id = str(uuid.uuid4())
        lts_storage_path = "purposefully/not/what/we/would/calculate/to/prove/this/is/used"

        def list_objects_func(path: str) -> List[str]:
            # this mock simulates a recording whose blob storage has been deleted by TTL
            # but which has been stored in LTS blob storage
            if path == lts_storage_path:
                return [
                    f"{lts_storage_path}/1-2",
                    f"{lts_storage_path}/3-4",
                ]
            else:
                return []

        mock_list_objects.side_effect = list_objects_func

        # this recording was shared several days ago, it has been stored in LTS storage
        SessionRecording.objects.create(
            team=self.team,
            session_id=session_id,
            storage_version="2023-08-01",
            object_storage_path=lts_storage_path,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/{session_id}/snapshots?version=2")
        response_data = response.json()

        assert mock_list_objects.call_args_list == [
            call(lts_storage_path),
        ]

        assert response_data == {
            "sources": [
                {
                    "blob_key": "1-2",
                    "source": "blob",
                    "start_timestamp": "1970-01-01T00:00:00.001000Z",
                    "end_timestamp": "1970-01-01T00:00:00.002000Z",
                },
                {
                    "blob_key": "3-4",
                    "source": "blob",
                    "start_timestamp": "1970-01-01T00:00:00.003000Z",
                    "end_timestamp": "1970-01-01T00:00:00.004000Z",
                },
            ],
        }

    @patch("posthog.session_recordings.session_recording_api.requests.get")
    @patch("posthog.session_recordings.session_recording_api.object_storage.get_presigned_url")
    @patch("posthog.session_recordings.session_recording_api.object_storage.list_objects")
    def test_2023_08_01_version_stored_snapshots_can_be_loaded(
        self, mock_list_objects: MagicMock, mock_get_presigned_url: MagicMock, mock_requests: MagicMock
    ) -> None:
        session_id = str(uuid.uuid4())
        lts_storage_path = "purposefully/not/what/we/would/calculate/to/prove/this/is/used"

        def list_objects_func(path: str) -> List[str]:
            # this mock simulates a recording whose blob storage has been deleted by TTL
            # but which has been stored in LTS blob storage
            if path == lts_storage_path:
                return [
                    f"{lts_storage_path}/1-2",
                    f"{lts_storage_path}/3-4",
                ]
            else:
                return []

        mock_list_objects.side_effect = list_objects_func
        mock_get_presigned_url.return_value = "https://example.com"

        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.raw = "the file contents"

        # Set up the mock to work as a context manager
        mock_requests.return_value.__enter__.return_value = mock_response
        mock_requests.return_value.__exit__.return_value = None

        SessionRecording.objects.create(
            team=self.team,
            session_id=session_id,
            storage_version="2023-08-01",
            object_storage_path=lts_storage_path,
        )

        query_parameters = [
            "source=blob",
            "version=2",
            "blob_key=1-2",
        ]
        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/{session_id}/snapshots?{'&'.join(query_parameters)}"
        )
        response_data = response.content.decode("utf-8")

        assert mock_list_objects.call_args_list == []

        assert mock_get_presigned_url.call_args_list == [
            call(f"{lts_storage_path}/1-2", expiration=60),
        ]

        assert response_data == "the file contents"
