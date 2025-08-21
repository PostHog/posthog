from unittest.mock import patch, MagicMock

from freezegun import freeze_time
from rest_framework import status

from posthog.models import Team
from posthog.models.utils import uuid7
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest

# this is the utf-16 surrogate pass encoded, gzipped and base64 encoded version of the above
# see: https://github.com/PostHog/posthog/blob/8ff764bb573c6a98368b2ae3503890551a1c3842/posthog/session_recordings/session_recording_helpers.py#L277
legacy_compressed_original = "H4sIAMHMCWUC/9VWbXPSQBDen+L0k44FkvBS4JPV0rG+1Pex08owKQmQSgGTUMRO/7r67HOXQBFa/dQ6N3fJ3e3tPrv73Ca/fl7KllxIKLEkEslYRpg30T1x0D0piMtR37dkGz2AXCIpxpF08ezgLbCnprKD/kOO5bvsy1DeoaXyTPZw4lBa8lF25UjeygQSLWh8KVWseXIGy8dYPcDskzyXBuSeQtc+pPvWbgJ7PmQSGUBa7QaYp+gdOZU5xhkxBdidLaFSD12pQ5sPn3oYXejvorsYfSnDOwf7PiSq9LOGeQPNQ1xqjEDAnSpmZalwpUb5HiQLa7WrXhejRwwnRJEC5QQ6daVmY2k8yHBOELMpPI7yPMRoM5w5lRK0an4SjEOsPIF+E5kJNMyxNsZz4bPKaGaHVtMMuzH1bhNLjHnXojmhpSLkfSII5YE8RJxTNI14E9ZLjP4E/ibErAzoYjbByTHsFvE25p7mp4+54j3HuWV59WIACyP5irMvEM3P8gH82EO+d3HmjNaqiKeOGvU64vko516RMYiBUH2d57pD6vWx17836Cvki5OjP5LX8grsNrjeA+c3xlotFKHzblG7QFzms4w3E/P2Bn4pX76gt6DT+KA9gAd6AyJyT2fxNR91d4w1s64MnOM9oud657SpVrV7hWZ4GsGf0PpzDixbxFgDL7RG6X3UUVmio55avWuVtXdtQBQ9ezvWx31zfDNtBcx8ViblnSIdYb3Eu5XaiprY/M9Yk1SX8aFCfm/Teoi9PlHoXp3V5m8j4MF35VwDM3dtBLy1ERiRQ2E+Xz7h8ITyRrMZoHob2WRDPXMpPyLCcCmm56w/hkVTVLEhGXmQfzGy2m5uskZwdS+r494NnqWM/+EN1n3mN4a2U+BIc09MpTR1w5wLWSOVf+1r9l2bD+VrxKxorXwDBvWgK7SZyypvz84di29s8+b8A7MXeXXJhrY9aU7E/Ab6/OJ1iFqfC633/6t4ae/En+juGttqlLOoLv8bGRQV/hs5qGAeq6eiaeJtB7WizlyauvaYY5Oj0b+asdt1m++K7hf5V+Zs1B0x/1kNurDae2SscvUqZ1II3mdVa/lu/8/e319O3Z4XveO/AS7WeNOWCwAA"


class TestSessionRecordings(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    def setUp(self):
        super().setUp()

        # Create a new team each time to ensure no clashing between tests
        self.team = Team.objects.create(organization=self.organization, name="New Team")

    @freeze_time("2023-01-01T00:00:00Z")
    @patch(
        "posthog.session_recordings.session_recording_api.list_blocks",
        side_effect=Exception(
            "if the LTS loading works then we'll not call list_blocks, we throw in the mock to enforce this"
        ),
    )
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_get_snapshot_sources_blobby_v2_from_lts(
        self,
        _mock_feature_enabled: MagicMock,
        _mock_exists: MagicMock,
        _mock_v2_list_blocks: MagicMock,
    ) -> None:
        session_id = str(uuid7())

        SessionRecording.objects.create(
            team=self.team,
            session_id=session_id,
            deleted=False,
            storage_version="2023-08-01",
            full_recording_v2_path="s3://the_bucket/the_lts_path/the_session_uuid?range=0-3456",
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/{session_id}/snapshots?blob_v2=true&blob_v2_lts=true"
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        response_data = response.json()

        assert response_data == {
            "sources": [
                {
                    "source": "blob_v2",
                    "blob_key": "the_lts_path/the_session_uuid",
                    # it's ok for these to be None, since we don't use the data anyway
                    # and this key is the whole session
                    "start_timestamp": None,
                    "end_timestamp": None,
                },
            ]
        }

    @freeze_time("2023-01-01T00:00:00Z")
    @patch("posthog.session_recordings.session_recording_api.session_recording_v2_object_storage.client")
    @patch(
        "posthog.session_recordings.session_recording_api.list_blocks",
        side_effect=Exception(
            "if the LTS loading works then we'll not call list_blocks, we throw in the mock to enforce this"
        ),
    )
    @patch(
        "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.exists",
        return_value=True,
    )
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_get_snapshot_for_lts_source_blobby_v2(
        self,
        _mock_feature_enabled: MagicMock,
        _mock_exists: MagicMock,
        _mock_v2_list_blocks: MagicMock,
        mock_object_storage_client: MagicMock,
    ) -> None:
        session_id = str(uuid7())

        # Mock the client fetch_block method
        mock_client_instance = MagicMock()
        mock_object_storage_client.return_value = mock_client_instance
        mock_client_instance.fetch_block.side_effect = Exception(
            "if the LTS loading works then we'll not call fetch_block, we throw in the mock to enforce this"
        )
        mock_client_instance.fetch_file.return_value = """
            {"timestamp": 1000, "type": "snapshot1"}
            {"timestamp": 2000, "type": "snapshot2"}
        """

        SessionRecording.objects.create(
            team=self.team,
            session_id=session_id,
            deleted=False,
            storage_version="2023-08-01",
            full_recording_v2_path="s3://the_bucket/the_lts_path/the_session_uuid?range=0-3456",
        )

        response = self.client.get(
            f"/api/projects/{self.team.id}/session_recordings/{session_id}/snapshots?blob_v2=true&blob_v2_lts=true&source=blob_v2&blob_key=/the_lts_path/the_session_uuid"
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        assert (
            response.content
            == b"""
            {"timestamp": 1000, "type": "snapshot1"}
            {"timestamp": 2000, "type": "snapshot2"}
        """
        )
