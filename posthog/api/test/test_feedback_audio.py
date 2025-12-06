import json
import base64
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models.feedback_audio import FeedbackAudio


class TestFeedbackAudioAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.feedback_id = str(uuid4())

        # Sample audio data (small base64 encoded audio file)
        self.sample_audio_data = base64.b64encode(b"fake_audio_content").decode("utf-8")

        self.valid_payload = {
            "feedback_id": self.feedback_id,
            "audio_mime_type": "audio/webm; codecs=opus",
            "audio_size": 1024,  # 1KB
            "audio_data": self.sample_audio_data,
            "token": self.team.api_token,
        }

    def test_successful_audio_upload(self):
        """Test successful audio upload with valid data"""
        with patch.object(FeedbackAudio, "save_audio_data") as mock_save:
            response = self.client.post(
                "/api/feedback/audio/",
                data=json.dumps(self.valid_payload),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            response_data = response.json()

            self.assertTrue(response_data["success"])
            self.assertEqual(response_data["feedback_id"], self.feedback_id)
            self.assertIn("id", response_data)
            self.assertEqual(response_data["message"], "Audio feedback uploaded successfully")

            # Verify audio file was saved
            mock_save.assert_called_once()

    def test_upload_without_authentication(self):
        payload_without_token = self.valid_payload.copy()
        payload_without_token.pop("token")

        """Test upload fails without API token"""
        response = self.client.post(
            "/api/feedback/audio/",
            data=json.dumps(payload_without_token),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_upload_with_empty_audio_data(self):
        """Test upload fails with empty audio data"""
        payload = self.valid_payload.copy()
        payload["audio_data"] = ""

        response = self.client.post(
            "/api/feedback/audio/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()

        self.assertFalse(response_data["success"])
        self.assertIn("audio_data", response_data["errors"])

    def test_upload_with_invalid_team_token(self):
        payload = self.valid_payload.copy()
        payload["token"] = "invalid_token"

        response = self.client.post(
            "/api/feedback/audio/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_upload_with_invalid_mime_type(self):
        """Test upload fails with unsupported MIME type"""
        payload = self.valid_payload.copy()
        payload["audio_mime_type"] = "audio/invalid"

        response = self.client.post(
            "/api/feedback/audio/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()

        self.assertFalse(response_data["success"])
        self.assertIn("audio_mime_type", response_data["errors"])

    def test_upload_with_oversized_file(self):
        """Test upload fails with file size exceeding limit"""
        payload = self.valid_payload.copy()
        payload["audio_size"] = 11 * 1024 * 1024  # 11MB, over the 10MB limit

        response = self.client.post(
            "/api/feedback/audio/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()

        self.assertFalse(response_data["success"])
        self.assertIn("audio_size", response_data["errors"])

    def test_upload_with_invalid_uuid(self):
        """Test upload fails with invalid UUID format for feedback_id"""
        payload = self.valid_payload.copy()
        payload["feedback_id"] = "not-a-valid-uuid"

        response = self.client.post(
            "/api/feedback/audio/",
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_data = response.json()

        self.assertFalse(response_data["success"])
        self.assertIn("feedback_id", response_data["errors"])

    def test_download_audio_success(self):
        """Test successful audio download with proper authentication"""
        # Create feedback audio record directly in DB
        feedback_audio = FeedbackAudio.objects.create(
            team_id=self.team.id,
            feedback_id=self.feedback_id,
            audio_size=1024,
            content_type="audio/webm",
        )

        # Mock the audio data return
        mock_audio_data = b"mock_audio_file_content"
        with patch.object(FeedbackAudio, "get_audio_data") as mock_get_audio:
            mock_get_audio.return_value = mock_audio_data

            # Test download
            response = self.client.get(
                f"/api/feedback/audio/{feedback_audio.feedback_id}/download?token={self.team.api_token}"
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.content, mock_audio_data)
            self.assertEqual(response.get("Content-Type"), "audio/webm")

    def test_download_audio_invalid_uuid(self):
        """Test download fails with invalid UUID format"""
        response = self.client.get(f"/api/feedback/audio/not-a-valid-uuid/download?token={self.team.api_token}")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_download_audio_unauthenticated_user(self):
        """Test download fails when user is not authenticated"""
        self.client.logout()

        response = self.client.get(f"/api/feedback/audio/{self.feedback_id}/download?token={self.team.api_token}")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_download_audio_missing_token(self):
        """Test download fails when token is missing"""
        response = self.client.get(f"/api/feedback/audio/{self.feedback_id}/download")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_download_audio_invalid_token(self):
        """Test download fails with invalid token"""
        response = self.client.get(f"/api/feedback/audio/{self.feedback_id}/download?token=invalid_token")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_download_audio_not_found(self):
        """Test download fails when audio file doesn't exist"""
        non_existent_id = uuid4()

        response = self.client.get(f"/api/feedback/audio/{non_existent_id}/download?token={self.team.api_token}")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
