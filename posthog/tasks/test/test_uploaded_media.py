from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.models import UploadedMedia
from posthog.models.uploaded_media import ABANDONED_UPLOAD_AGE
from posthog.storage.object_storage import ObjectStorageError
from posthog.tasks.uploaded_media import _sweep_abandoned_media_upload, sweep_abandoned_media_uploads


class TestSweepAbandonedMediaUploads(APIBaseTest):
    def _create_media(self, *, pending: bool, age: timedelta) -> UploadedMedia:
        media = UploadedMedia.objects.create(
            team=self.team,
            created_by=self.user,
            file_name="logo.png",
            content_type="image/png",
            media_location=f"media_uploads/team-{self.team.pk}/staging/abandoned",
            purpose="email",
            pending=pending,
        )
        UploadedMedia.objects.filter(pk=media.pk).update(created_at=timezone.now() - age)
        return media

    @patch("posthog.tasks.uploaded_media.object_storage.delete")
    def test_sweeps_only_pending_rows_past_the_cutoff(self, mock_delete: MagicMock) -> None:
        abandoned = self._create_media(pending=True, age=ABANDONED_UPLOAD_AGE + timedelta(hours=1))
        still_in_flight = self._create_media(pending=True, age=timedelta(minutes=5))
        completed = self._create_media(pending=False, age=ABANDONED_UPLOAD_AGE + timedelta(days=30))

        assert sweep_abandoned_media_uploads() == 1

        assert not UploadedMedia.objects.filter(pk=abandoned.pk).exists()
        assert UploadedMedia.objects.filter(pk=still_in_flight.pk).exists()
        assert UploadedMedia.objects.filter(pk=completed.pk).exists()
        mock_delete.assert_called_once_with(abandoned.media_location)

    @patch("posthog.tasks.uploaded_media.object_storage.delete")
    def test_keeps_an_upload_completed_after_candidate_selection(self, mock_delete: MagicMock) -> None:
        completed = self._create_media(pending=True, age=ABANDONED_UPLOAD_AGE + timedelta(hours=1))
        cutoff = timezone.now() - ABANDONED_UPLOAD_AGE
        UploadedMedia.objects.filter(pk=completed.pk).update(pending=False)

        assert _sweep_abandoned_media_upload(completed.pk, cutoff) is False
        assert UploadedMedia.objects.filter(pk=completed.pk).exists()
        mock_delete.assert_not_called()

    @patch("posthog.tasks.uploaded_media.object_storage.delete", side_effect=ObjectStorageError("delete failed"))
    def test_keeps_the_row_when_its_object_cannot_be_deleted(self, _mock_delete: MagicMock) -> None:
        abandoned = self._create_media(pending=True, age=ABANDONED_UPLOAD_AGE + timedelta(hours=1))

        assert sweep_abandoned_media_uploads() == 0
        assert UploadedMedia.objects.filter(pk=abandoned.pk).exists()
