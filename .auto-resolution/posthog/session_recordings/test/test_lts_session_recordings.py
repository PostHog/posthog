import uuid

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest
from unittest.mock import MagicMock, call, patch

from posthog.models import Team
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.test import setup_stream_from

# this is the utf-16 surrogate pass encoded, gzipped and base64 encoded version of the above
# see: https://github.com/PostHog/posthog/blob/8ff764bb573c6a98368b2ae3503890551a1c3842/posthog/session_recordings/session_recording_helpers.py#L277
legacy_compressed_original = "H4sIAMHMCWUC/9VWbXPSQBDen+L0k44FkvBS4JPV0rG+1Pex08owKQmQSgGTUMRO/7r67HOXQBFa/dQ6N3fJ3e3tPrv73Ca/fl7KllxIKLEkEslYRpg30T1x0D0piMtR37dkGz2AXCIpxpF08ezgLbCnprKD/kOO5bvsy1DeoaXyTPZw4lBa8lF25UjeygQSLWh8KVWseXIGy8dYPcDskzyXBuSeQtc+pPvWbgJ7PmQSGUBa7QaYp+gdOZU5xhkxBdidLaFSD12pQ5sPn3oYXejvorsYfSnDOwf7PiSq9LOGeQPNQ1xqjEDAnSpmZalwpUb5HiQLa7WrXhejRwwnRJEC5QQ6daVmY2k8yHBOELMpPI7yPMRoM5w5lRK0an4SjEOsPIF+E5kJNMyxNsZz4bPKaGaHVtMMuzH1bhNLjHnXojmhpSLkfSII5YE8RJxTNI14E9ZLjP4E/ibErAzoYjbByTHsFvE25p7mp4+54j3HuWV59WIACyP5irMvEM3P8gH82EO+d3HmjNaqiKeOGvU64vko516RMYiBUH2d57pD6vWx17836Cvki5OjP5LX8grsNrjeA+c3xlotFKHzblG7QFzms4w3E/P2Bn4pX76gt6DT+KA9gAd6AyJyT2fxNR91d4w1s64MnOM9oud657SpVrV7hWZ4GsGf0PpzDixbxFgDL7RG6X3UUVmio55avWuVtXdtQBQ9ezvWx31zfDNtBcx8ViblnSIdYb3Eu5XaiprY/M9Yk1SX8aFCfm/Teoi9PlHoXp3V5m8j4MF35VwDM3dtBLy1ERiRQ2E+Xz7h8ITyRrMZoHob2WRDPXMpPyLCcCmm56w/hkVTVLEhGXmQfzGy2m5uskZwdS+r494NnqWM/+EN1n3mN4a2U+BIc09MpTR1w5wLWSOVf+1r9l2bD+VrxKxorXwDBvWgK7SZyypvz84di29s8+b8A7MXeXXJhrY9aU7E/Ab6/OJ1iFqfC633/6t4ae/En+juGttqlLOoLv8bGRQV/hs5qGAeq6eiaeJtB7WizlyauvaYY5Oj0b+asdt1m++K7hf5V+Zs1B0x/1kNurDae2SscvUqZ1II3mdVa/lu/8/e319O3Z4XveO/AS7WeNOWCwAA"


class TestSessionRecordings(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        # Create a new team each time to ensure no clashing between tests
        self.team = Team.objects.create(organization=self.organization, name="New Team")

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.object_storage.list_objects")
    def test_2023_08_01_version_stored_snapshots_can_be_gathered(
        self, mock_list_objects: MagicMock, _mock_exists: MagicMock
    ) -> None:
        session_id = str(uuid.uuid4())
        lts_storage_path = "purposefully/not/what/we/would/calculate/to/prove/this/is/used"

        def list_objects_func(path: str) -> list[str]:
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

    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthog.session_recordings.session_recording_api.stream_from", return_value=setup_stream_from())
    @patch("posthog.session_recordings.session_recording_api.object_storage.get_presigned_url")
    @patch("posthog.session_recordings.session_recording_api.object_storage.list_objects")
    def test_2023_08_01_version_stored_snapshots_can_be_loaded(
        self,
        mock_list_objects: MagicMock,
        mock_get_presigned_url: MagicMock,
        _mock_stream_from: MagicMock,
        _mock_exists: MagicMock,
    ) -> None:
        session_id = str(uuid.uuid4())
        lts_storage_path = "purposefully/not/what/we/would/calculate/to/prove/this/is/used"

        def list_objects_func(path: str) -> list[str]:
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

        assert response_data == "Example content"
