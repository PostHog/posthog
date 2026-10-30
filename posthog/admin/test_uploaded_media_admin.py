from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin.models import CHANGE, LogEntry
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from posthog.models import UploadedMedia
from posthog.storage.object_storage import ObjectStorageError


class TestUploadedMediaAdminServingActions(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        self.changelist = reverse("admin:posthog_uploadedmedia_changelist")
        self.target = UploadedMedia.objects.create(
            team=self.team, file_name="mistake.png", purpose="email", media_location="media_uploads/target"
        )
        self.bystander = UploadedMedia.objects.create(
            team=self.team, file_name="keep.png", purpose="email", media_location="media_uploads/bystander"
        )

    def _run_action(self, action: str, *media: UploadedMedia) -> None:
        response = self.client.post(
            self.changelist, {"action": action, "_selected_action": [str(item.id) for item in media or [self.target]]}
        )
        self.assertEqual(response.status_code, 302)

    def _log_messages(self, media: UploadedMedia) -> list[str]:
        return list(
            LogEntry.objects.filter(object_id=str(media.id), action_flag=CHANGE)
            .order_by("action_time")
            .values_list("change_message", flat=True)
        )

    def test_staff_can_stop_and_resume_serving_one_image_with_an_audit_entry(self) -> None:
        self._run_action("disable_serving")

        assert UploadedMedia.objects.get(id=self.target.id).serving_disabled_at is not None
        assert UploadedMedia.objects.get(id=self.bystander.id).serving_disabled_at is None

        self._run_action("enable_serving")

        assert UploadedMedia.objects.get(id=self.target.id).serving_disabled_at is None
        assert self._log_messages(self.target) == [
            "Stopped serving at the public URL.",
            "Resumed serving at the public URL.",
        ]

    @override_settings(
        UPLOADED_MEDIA_PUBLIC_URL="https://media.example.com",
        UPLOADED_MEDIA_CDN_PURGE_ZONE_ID="zone-for-tests",
        UPLOADED_MEDIA_CDN_PURGE_TOKEN="fake-token-for-tests",
    )
    @patch("posthog.storage.uploaded_media_cdn.purge_urls")
    @patch("posthog.models.uploaded_media.object_storage.delete")
    def test_delete_removes_the_bytes_of_stopped_images_only_and_purges_their_cdn_url(
        self, delete_object, purge_urls
    ) -> None:
        UploadedMedia.objects.filter(id=self.target.id).update(serving_disabled_at=timezone.now())

        self._run_action("delete_stored_file", self.target, self.bystander)

        self.target.refresh_from_db()
        self.bystander.refresh_from_db()
        delete_object.assert_called_once_with("media_uploads/target")
        assert self.target.media_location is None
        assert self.bystander.media_location == "media_uploads/bystander"
        assert self._log_messages(self.target) == ["Deleted the stored file permanently."]
        assert purge_urls.call_args.args == ([f"https://media.example.com/uploaded_media/{self.target.id}"],)

    @patch("posthog.models.uploaded_media.object_storage.delete", side_effect=ObjectStorageError("delete failed"))
    def test_failed_delete_keeps_the_location_so_staff_can_retry(self, _delete_object) -> None:
        UploadedMedia.objects.filter(id=self.target.id).update(serving_disabled_at=timezone.now())

        self._run_action("delete_stored_file")

        self.target.refresh_from_db()
        assert self.target.media_location == "media_uploads/target"
        assert self._log_messages(self.target) == []
