from posthog.test.base import BaseTest

from django.contrib.admin.models import CHANGE, LogEntry
from django.urls import reverse

from posthog.models import UploadedMedia


class TestUploadedMediaAdminServingActions(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        self.changelist = reverse("admin:posthog_uploadedmedia_changelist")
        self.target = UploadedMedia.objects.create(team=self.team, file_name="mistake.png", purpose="email")
        self.bystander = UploadedMedia.objects.create(team=self.team, file_name="keep.png", purpose="email")

    def _run_action(self, action: str) -> None:
        response = self.client.post(self.changelist, {"action": action, "_selected_action": [str(self.target.id)]})
        self.assertEqual(response.status_code, 302)

    def test_staff_can_stop_and_resume_serving_one_image_with_an_audit_entry(self) -> None:
        self._run_action("disable_serving")

        self.target.refresh_from_db()
        self.bystander.refresh_from_db()
        assert self.target.serving_disabled_at is not None
        assert self.bystander.serving_disabled_at is None

        self._run_action("enable_serving")

        self.target.refresh_from_db()
        assert self.target.serving_disabled_at is None
        messages = list(
            LogEntry.objects.filter(object_id=str(self.target.id), action_flag=CHANGE)
            .order_by("action_time")
            .values_list("change_message", flat=True)
        )
        assert messages == ["Stopped serving at the public URL.", "Resumed serving at the public URL."]
